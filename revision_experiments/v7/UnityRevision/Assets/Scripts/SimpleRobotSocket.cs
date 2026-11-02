using System.Collections;
using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System;
using System.Globalization;
using System.Linq;
using System.Collections.Generic;
using System.IO;

public partial class SimpleRobotSocket : MonoBehaviour
{
    [Header("Core components")]
    public CCD_IK_Solver ikSolver;

    [Header("Cameras")]
    public Camera cameraMain;
    public Camera cameraAux;
    public string pythonServerIP = "127.0.0.1";
    public int pythonServerPort = 5506;

    [Header("Scene objects")]
    public Transform targetCube;
    public Transform tablePoint;
    public Transform ikTarget;
    public Transform gripperCenter;

    [Header("Motion and grasp parameters")]
    public float moveSpeed = 0.15f;  // reduced from 0.2 to limit transport acceleration
    public float baseRotationSpeed = 30f;
    public float graspThreshold = 0.12f;  // search radius around the fingertip centre (m)
    public float graspHeightOffset = 0.0f;  // fingers close on the object sides rather than its top
    public float gripperTipYOffset = 0.0f;  // wrist-to-fingertip vertical offset; 0 disables the compensation
    public float placeHoverHeight = 0.15f;
    public float placeDropHeight = 0.02f;  // release height above the container (m)

    [Header("Physical verification")]
    public float breakForce = 50f;
    public float liftTestHeight = 0.05f;     // tolerates elastic stretch of the FixedJoint (about 3-8 mm)
    public float liftTestSpeed = 0.05f;
    public int requiredContactCount = 2;

    [Header("Disturbance injection")]
    public float preGraspOffsetRange = 0.05f;
    public float midTransportDropForce = 100f;
    public float containerShiftRange = 0.08f;

    [Header("Wrist locking")]
    public Transform wristBone;
    public Transform robotBaseYawNode;

    // Values reported in the JSON status messages
    private int lastContactCount = 0;
    private float lastDeltaY = 0f;
    private float lastGQS = 0f;
    private float lastBBoxOverlap = 0f;
    private string lastBBoxContainerName = "";

    // Original mass properties of the grasped object; the centre of mass and angular drag are changed
    // while it is held and restored on release.
    private Vector3 savedOriginalCenterOfMass;
    private float savedOriginalAngularDrag;
    private bool hasSavedPhysicsProps = false;
    // Colliders of the grasped object that are disabled while the grasp settles
    private Dictionary<Collider, bool> _savedColliderStates = new Dictionary<Collider, bool>();
    private TcpListener server;
    private bool isRunning = true;
    private string pendingAction = "";
    private object actionLock = new object();

    // File log: the Python side sets the directory with LOG_DIR; static so that it survives scene reloads
    private static string logFilePath = "";
    private static StreamWriter logWriter = null;
    private static readonly object logLock = new object();
    private static bool logHandlerRegistered = false;

    // Proxy anchor: gripperCenter has lossyScale (0,0,0) inside the gantry hierarchy, which breaks
    // InverseTransformPoint and the FixedJoint coordinate conversion; a separate unit-scale object
    // is used as the connected body instead.
    private GameObject jointProxyAnchor;
    private Rigidbody jointProxyRB;

    // Initial poses of all graspable objects (used by RESET_SCENE)
    private System.Collections.Generic.Dictionary<GameObject, (Vector3 pos, Quaternion rot)> initialPoses
        = new System.Collections.Generic.Dictionary<GameObject, (Vector3, Quaternion)>();

    void Start()
    {
        // A copied scene can serialize the old 5006 value; enforce the isolated ports.
        pythonServerIP = "127.0.0.1";
        pythonServerPort = revisionFeedbackPort;

        // Wrist lock: the IK solver skips the wrist joint while skipWristRotation is set
        if (wristBone != null && ikSolver != null)
            ikSolver.wristBone = wristBone;
        if (ikTarget != null)
        {
            foreach (var mr in ikTarget.GetComponentsInChildren<MeshRenderer>()) mr.enabled = false;
        }

        new Thread(() => {
            try
            {
                server = new TcpListener(IPAddress.Loopback, revisionCommandPort);
                server.Start();
                Debug.Log("Unity server ready, waiting for commands");
            }
            catch (Exception e)
            {
                Debug.LogError("Port binding failed: " + e.Message);
                return;
            }

            while (isRunning)
            {
                try
                {
                    TcpClient client = server.AcceptTcpClient();
                    using (client)
                    using (NetworkStream stream = client.GetStream())
                    {
                        stream.ReadTimeout = 5000;
                        using (var framed = new System.IO.MemoryStream())
                        {
                            byte[] buffer = new byte[4096];
                            int len;
                            while ((len = stream.Read(buffer, 0, buffer.Length)) > 0)
                            {
                                framed.Write(buffer, 0, len);
                                if (framed.Length > 65536) throw new System.IO.IOException("Oversized command");
                            }
                            string msg = Encoding.UTF8.GetString(framed.ToArray());
                            lock (actionLock) { pendingAction = msg; }
                        }
                    }
                }
                catch (Exception e)
                {
                    if (isRunning) Debug.LogWarning("Communication error: " + e.Message);
                }
            }
        })
        { IsBackground = true }.Start();

        if (ikSolver) ikSolver.isIkActive = false;

        // Record initial poses of graspable objects (for RESET_SCENE)
        SaveInitialPoses();
        SaveRevisionContainers();

        // Proxy anchor outside the gantry hierarchy with unit scale
        jointProxyAnchor = new GameObject("JointProxyAnchor");
        jointProxyAnchor.transform.SetParent(null); // scene root, no inherited zero scale
        jointProxyAnchor.transform.localScale = Vector3.one;
        jointProxyRB = jointProxyAnchor.AddComponent<Rigidbody>();
        jointProxyRB.isKinematic = true;
        jointProxyRB.useGravity = false;

        // Route all Debug.Log/LogWarning/LogError messages to unity.log; reopen the writer after a scene reload
        lock (logLock)
        {
            if (logWriter == null && !string.IsNullOrEmpty(logFilePath))
            {
                try
                {
                    logWriter = new StreamWriter(logFilePath, true, Encoding.UTF8);
                    Debug.Log($"[file log] resumed after scene reload: {logFilePath}");
                }
                catch (Exception e)
                {
                    Debug.LogError($"Could not resume the file log: {e.Message}");
                }
            }
            if (!logHandlerRegistered)
            {
                Application.logMessageReceived += OnUnityLogMessage;
                logHandlerRegistered = true;
            }
        }
    }

    void OnUnityLogMessage(string logString, string stackTrace, LogType type)
    {
        lock (logLock)
        {
            if (logWriter != null)
            {
                string timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
                string level = type == LogType.Error ? "ERROR" :
                               type == LogType.Warning ? "WARN" : "INFO";
                logWriter.WriteLine($"[{timestamp}] [{level}] {logString}");
                if (type == LogType.Error && !string.IsNullOrEmpty(stackTrace))
                {
                    logWriter.WriteLine($"  StackTrace: {stackTrace}");
                }
                logWriter.Flush();
            }
        }
    }

    void HandleLogDir(string dirPath)
    {
        lock (logLock)
        {
            // Unregister the previous log hook
            if (logHandlerRegistered)
            {
                Application.logMessageReceived -= OnUnityLogMessage;
                logHandlerRegistered = false;
            }

            // Close the previous writer, if any
            if (logWriter != null)
            {
                logWriter.Flush();
                logWriter.Close();
                logWriter = null;
            }

            try
            {
                if (!Directory.Exists(dirPath))
                    Directory.CreateDirectory(dirPath);

                logFilePath = Path.Combine(dirPath, "unity.log");
                logWriter = new StreamWriter(logFilePath, true, Encoding.UTF8) { AutoFlush = false };
                // Start marker
                logWriter.WriteLine($"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] [INFO] Unity file log enabled");
                logWriter.Flush();
                Debug.Log($"[file log] enabled: {logFilePath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"Could not create the Unity log file: {e.Message}");
                logWriter = null;
                logFilePath = "";
            }

            // Register the log hook again
            if (!logHandlerRegistered)
            {
                Application.logMessageReceived += OnUnityLogMessage;
                logHandlerRegistered = true;
            }
        }
    }

    void SaveInitialPoses()
    {
        initialPoses.Clear();
        Rigidbody[] allRigidbodies = FindObjectsOfType<Rigidbody>();
        foreach (Rigidbody rb in allRigidbodies)
        {
            // Only small graspable objects (tables, floor and robot links are skipped)
            if (rb.isKinematic) continue;
            if (rb.transform.IsChildOf(this.transform)) continue;
            string nameUp = rb.name.ToUpper();
            if (nameUp.Contains("TABLE") || nameUp.Contains("FLOOR") || nameUp.Contains("PLANE") || nameUp.Contains("WALL"))
                continue;

            initialPoses[rb.gameObject] = (rb.transform.position, rb.transform.rotation);
            Debug.Log($"[scene snapshot] initial pose of {rb.name}: pos={rb.transform.position}");
        }
    }

    // Original command string (case preserved) for DISTURB target names
    private string originalAction = "";

    void Update()
    {
        string actionToExecute = "";
        lock (actionLock)
        {
            if (!string.IsNullOrEmpty(pendingAction))
            {
                originalAction = new string(pendingAction.Where(c => !char.IsControl(c)).ToArray()).Trim();
                actionToExecute = originalAction.ToUpper();
                pendingAction = "";
            }
        }

        if (!string.IsNullOrEmpty(actionToExecute))
        {
            if (!actionToExecute.StartsWith("REV_")) StopAllCoroutines();
            StartCoroutine(ProcessCommand(actionToExecute));
        }
    }

    void FixedUpdate()
    {
        // Move the proxy anchor with Rigidbody.MovePosition/MoveRotation so that the joint constraint
        // is carried over continuously; SetPositionAndRotation would teleport it.
        if (jointProxyRB != null && gripperCenter != null)
        {
            jointProxyRB.MovePosition(gripperCenter.position);
            // Rotation is not synchronised while an object is held: following the arm orientation would rotate
            // irregular objects into the gripper fingers.
            if (ikSolver == null || !ikSolver.skipWristRotation)
                jointProxyRB.MoveRotation(gripperCenter.rotation);
        }
    }

    void OnApplicationQuit()
    {
        isRunning = false;
        if (server != null)
        {
            try { server.Stop(); } catch (Exception) { }
        }
        CloseLogWriter();
    }

    void OnDestroy()
    {
        // Stop the TCP listener when the scene is unloaded; Start() binds the port again
        isRunning = false;
        if (server != null)
        {
            try { server.Stop(); } catch (Exception) { }
        }
        // The log writer is kept across scene changes and closed only in OnApplicationQuit
    }

    void CloseLogWriter()
    {
        lock (logLock)
        {
            if (logWriter != null)
            {
                if (logHandlerRegistered)
                {
                    Application.logMessageReceived -= OnUnityLogMessage;
                    logHandlerRegistered = false;
                }
                logWriter.Flush();
                logWriter.Close();
                logWriter = null;
                logFilePath = "";
            }
        }
    }

    IEnumerator ProcessCommand(string upperAction)
    {
        // Revision commands are handled before IK and do not change the robot pose.
        if (upperAction.StartsWith("REV_"))
        {
            yield return StartCoroutine(ExecuteRevisionCommand(originalAction));
            yield break;
        }
        if (upperAction.StartsWith("DISTURB:"))
        {
            SendStatusToPython("REV_ERROR:Legacy injection disabled; use scheduled REV_DISTURB events.");
            yield break;
        }

        if (!ikSolver.isIkActive)
        {
            ikTarget.position = gripperCenter.position;
            ikSolver.isIkActive = true;
        }

        if (upperAction.StartsWith("LOG_DIR:"))
        {
            // Log directory sent by the Python side; enables the file log
            string dirPath = originalAction.Substring("LOG_DIR:".Length).Trim();
            HandleLogDir(dirPath);
        }
        else if (upperAction.Contains("REQUEST_IMAGE"))
        {
            Debug.Log("[capture] request received, rendering camera images");
            yield return StartCoroutine(CaptureAndSendImage());
        }
        else if (upperAction.StartsWith("DISTURB:"))
        {
            // Disturbance injection (inline)
            // originalAction keeps the target name in its original case
            string disturbCmd = originalAction.Substring("DISTURB:".Length).Trim();
            yield return StartCoroutine(ExecuteDisturbance(disturbCmd));
        }
        else if (upperAction.StartsWith("BLIND_PICK:") || upperAction.StartsWith("ADJUST:"))
        {
            revisionGraspFailure="";lastContactCount=0;lastDeltaY=0;lastGQS=0;
            // Format: BLIND_PICK:x,y,z|TargetName  or  BLIND_PICK:x,y,z
            string cmdBody = originalAction.Substring(originalAction.IndexOf(':') + 1).Trim();
            string targetName = "";
            int pipeIdx = cmdBody.IndexOf('|');
            string coordStr = pipeIdx >= 0 ? cmdBody.Substring(0, pipeIdx).Trim() : cmdBody.Trim();
            if (pipeIdx >= 0) targetName = cmdBody.Substring(pipeIdx + 1).Trim();

            string[] parts = coordStr.Split(',');
            if (parts.Length == 3)
            {
                float absX = float.Parse(parts[0].Trim(), CultureInfo.InvariantCulture);
                // Surface height of the object supplied by the Python side
                float absY = float.Parse(parts[1].Trim(), CultureInfo.InvariantCulture);
                float absZ = float.Parse(parts[2].Trim(), CultureInfo.InvariantCulture);

                Vector3 safePos = ikTarget.position + Vector3.up * 0.15f;
                yield return StartCoroutine(MoveToPos(safePos));

                // gripperCenter is the wrist pivot; the fingertips are gripperTipYOffset below it.
                // Grasp height = object surface + safety margin + wrist-to-fingertip offset
                float safeGraspY = absY + graspHeightOffset + gripperTipYOffset;
                float fingertipY = safeGraspY - gripperTipYOffset; // fingertip height

                Debug.Log($"[grasp height] surface Y={absY:F3}, wrist Y={safeGraspY:F3}, fingertip Y={fingertipY:F3}");

                Vector3 visualHoverPos = new Vector3(absX, safeGraspY + placeHoverHeight, absZ);
                yield return StartCoroutine(MoveToPos(visualHoverPos));

                Vector3 visualGraspPos = new Vector3(absX, safeGraspY, absZ);
                yield return StartCoroutine(MoveToPos(visualGraspPos));

                // Guard: if an object is still attached (e.g. after an incomplete PLACE_FAILED clean-up),
                // release it before grasping a new target so that two objects are never attached.
                if (IsStillHolding())
                {
                    Debug.LogWarning($"[guard] gripper still holds '{targetCube.name}'; releasing it before grasping '{targetName}'");
                    FixedJoint oldJoint = targetCube.GetComponent<FixedJoint>();
                    if (oldJoint != null) Destroy(oldJoint);
                    Rigidbody oldRb = targetCube.GetComponent<Rigidbody>();
                    if (oldRb != null)
                    {
                        if (hasSavedPhysicsProps)
                        {
                            oldRb.centerOfMass = savedOriginalCenterOfMass;
                            oldRb.angularDrag = savedOriginalAngularDrag;
                            hasSavedPhysicsProps = false;
                        }
                        oldRb.isKinematic = false;
                        oldRb.useGravity = true;
                        oldRb.velocity = Vector3.zero;
                        oldRb.angularVelocity = Vector3.zero;
                        oldRb.WakeUp();
                    }
                    RestoreTargetColliders();
                    if (ikSolver != null) ikSolver.skipWristRotation = false;
                    Debug.Log($"[guard] '{targetCube.name}' released; grasping '{targetName}'");
                }

                // Grasp with retries (tolerates position error, widens the search)
                targetCube = null;  // cleared before the retries
                yield return StartCoroutine(TryBlindGraspWithRetry(targetName, visualGraspPos));

                if (targetCube != null)
                {
                    // AttachCubeToGripper aligns the object kinematically and creates the FixedJoint;
                    // wait one physics step before making the object dynamic again
                    yield return new WaitForFixedUpdate();
                    if (targetCube != null)
                    {
                        Rigidbody rb = targetCube.GetComponent<Rigidbody>();
                        if (rb != null && rb.isKinematic)
                        {
                            rb.isKinematic = false;
                            rb.velocity = Vector3.zero;
                            rb.angularVelocity = Vector3.zero;
                            rb.WakeUp();
                            Debug.Log($"[diag] {targetCube.name} kinematic->false, velocity reset, pos={targetCube.position:F4}");
                        }
                    }
                    // Diagnostics: per-frame monitoring for 0.2 s after the object becomes dynamic
                    yield return StartCoroutine(DiagnosticPostKinematicMonitor());

                    // Restore the target colliders once the grasp has settled
                    RestoreTargetColliders();

                    // Lift test
                    yield return StartCoroutine(PerformLiftTest());

                    if (GraspContract.LiftPasses(lastDeltaY,liftTestHeight))
                    {
                        // Lift test passed: the grasp is confirmed physically
                        Vector3 retreatPos = gripperCenter.position + Vector3.up * 0.15f;
                        yield return StartCoroutine(MoveToPos(retreatPos));

                        // breakForce stays infinite during transport, centring and release; a 50 N threshold caused
                        // spurious joint breaks under transport accelerations. The joint is destroyed explicitly on release.

                        if (upperAction.StartsWith("ADJUST"))
                            Debug.Log("[grasp] re-grasp after correction succeeded");
                        else
                        {
                            string capturedName = targetCube != null ? targetCube.name : "unknown";
                            string targetSuffix = string.IsNullOrEmpty(targetName) ? "" : string.Format(" (target: {0})", targetName);
                            Debug.LogFormat("[grasp] succeeded: {0}{1}", capturedName, targetSuffix);
                        }

                        SendStatusToPython(BuildGraspSuccessJson());
                    }
                    else
                    {
                        revisionGraspFailure="lift_below_threshold";
                        Debug.LogWarning($"[lift test] failed: deltaY={lastDeltaY:F4} m, required {GraspContract.RequiredLift(liftTestHeight):F4} m");
                        if (targetCube != null)
                        {
                            // Restore the original mass properties
                            Rigidbody failRb = targetCube.GetComponent<Rigidbody>();
                            if (failRb != null && hasSavedPhysicsProps)
                            {
                                failRb.centerOfMass = savedOriginalCenterOfMass;
                                failRb.angularDrag = savedOriginalAngularDrag;
                                hasSavedPhysicsProps = false;
                            }
                            // Restore the target colliders on the failure path as well
                            RestoreTargetColliders();
                            // Unlock the wrist and release the object
                            if (ikSolver != null)
                                ikSolver.skipWristRotation = false;
                            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
                            if (joint != null) Destroy(joint);
                            targetCube = null;
                        }
                        SendStatusToPython(BuildGraspFailedJson());
                    }
                }
                else
                {
                    Debug.LogWarning("No physical object found at the given coordinates; all retries failed.");
                    SendStatusToPython(BuildGraspFailedJson());
                }
            }
        }
        else if (upperAction.StartsWith("BLIND_PLACE:"))
        {
            if (targetCube == null || !IsStillHolding())
            {
                Debug.LogError("No object is held (FixedJoint missing or broken); cannot place");
                SendStatusToPython(BuildPlaceFailedJson());
                yield break;
            }

            // Format: BLIND_PLACE:x,y,z|TargetName (the suffix after | is removed first)
            string cmdBody = originalAction.Substring(originalAction.IndexOf(':') + 1).Trim();
            string placeTargetName = "";
            int pipeIdx = cmdBody.IndexOf('|');
            string coordStr = pipeIdx >= 0 ? cmdBody.Substring(0, pipeIdx).Trim() : cmdBody.Trim();
            if (pipeIdx >= 0) placeTargetName = cmdBody.Substring(pipeIdx + 1).Trim();

            string[] parts = coordStr.Split(',');
            if (parts.Length == 3)
            {
                float absX = float.Parse(parts[0].Trim(), CultureInfo.InvariantCulture);
                // Container floor height supplied by the Python side
                float absY = float.Parse(parts[1].Trim(), CultureInfo.InvariantCulture);
                float absZ = float.Parse(parts[2].Trim(), CultureInfo.InvariantCulture);

                // Hover and release relative to the container height. The wrist is raised by gripperTipYOffset,
                // as in the grasp, so that the object is released at the same height.
                float dropY = absY + placeDropHeight + gripperTipYOffset;
                float hoverY = absY + placeHoverHeight + gripperTipYOffset;

                Debug.Log($"[place height] container floor Y={absY:F3}, wrist release Y={dropY:F3}, object release Y={dropY - gripperTipYOffset:F3}");

                Vector3 dropPos = new Vector3(absX, dropY, absZ);
                Vector3 hoverPos = new Vector3(absX, hoverY, absZ);

                yield return StartCoroutine(MoveToPos(hoverPos, true));

                if (!IsStillHolding())
                {
                    Debug.LogWarning("[transport] FixedJoint broken; object dropped");
                    SendStatusToPython(BuildPlaceFailedJson());
                    yield break;
                }

                // Container centring: raycast to the container and adjust XZ to its centre
                RaycastHit containerHit;
                Debug.Log($"[place diag] initial hoverPos=({hoverPos.x:F4}, {hoverPos.y:F4}, {hoverPos.z:F4})");
                if (Physics.Raycast(hoverPos, Vector3.down, out containerHit, 0.5f))
                {
                    string hitName = containerHit.collider.name.ToUpper();
                    Vector3 hitPoint = containerHit.point;
                    Vector3 boundsCenter = containerHit.collider.bounds.center;
                    Vector3 boundsSize = containerHit.collider.bounds.size;
                    Vector3 boundsMin = containerHit.collider.bounds.min;
                    Vector3 boundsMax = containerHit.collider.bounds.max;
                    float distFromBoundsCenter = new Vector2(hitPoint.x - boundsCenter.x, hitPoint.z - boundsCenter.z).magnitude;

                    Debug.Log($"[place diag] ray hit '{containerHit.collider.name}' at ({hitPoint.x:F4}, {hitPoint.y:F4}, {hitPoint.z:F4})");
                    Debug.Log($"[place diag] container bounds: center=({boundsCenter.x:F4}, {boundsCenter.z:F4}) size=({boundsSize.x:F4}, {boundsSize.z:F4}) min=({boundsMin.x:F4}, {boundsMin.z:F4}) max=({boundsMax.x:F4}, {boundsMax.z:F4})");
                    Debug.Log($"[place diag] hit distance from bounds centre={distFromBoundsCenter:F4} m, margin to edge={(boundsSize.x/2f - Mathf.Abs(hitPoint.x - boundsCenter.x)):F4} m (X), {(boundsSize.z/2f - Mathf.Abs(hitPoint.z - boundsCenter.z)):F4} m (Z)");

                    if (hitName.Contains("PLATE") || hitName.Contains("BOWL") || hitName.Contains("BOX") ||
                        hitName.Contains("CONTAINER") || hitName.Contains("DISH") || hitName.Contains("TRAY") || hitName.Contains("CUP"))
                    {
                        Vector3 containerCenter = containerHit.collider.bounds.center;
                        float correctionX = containerCenter.x - hoverPos.x;
                        float correctionZ = containerCenter.z - hoverPos.z;
                        Debug.Log($"[centring] ray hit '{containerHit.collider.name}', bounds centre=({containerCenter.x:F3},{containerCenter.z:F3}); correction dX={correctionX:F4} m dZ={correctionZ:F4} m");

                        hoverPos.x = containerCenter.x;
                        hoverPos.z = containerCenter.z;
                        dropPos.x = containerCenter.x;
                        dropPos.z = containerCenter.z;

                        // Move to the centred hover position
                        yield return StartCoroutine(MoveToPos(hoverPos));
                        Debug.Log($"[place diag] centred hoverPos=({hoverPos.x:F4}, {hoverPos.y:F4}, {hoverPos.z:F4})");
                    }
                    else
                    {
                        Debug.Log($"[centring] ray hit '{containerHit.collider.name}', which is not a container (PLATE/BOWL/BOX/CONTAINER/DISH/TRAY/CUP); centring skipped");
                    }
                }
                else
                {
                    Debug.LogWarning("[centring] nothing below the gripper; using the commanded coordinates");
                }

                yield return StartCoroutine(MoveToPos(dropPos));
                yield return new WaitForSeconds(0.2f);

                // Keep the object reference for the post-release check
                Transform releasedObject = targetCube;

                // Transport integrity check (non-blocking)
                if (targetCube != null && !IsStillHolding())
                    Debug.LogWarning("[transport] FixedJoint broke during transport; the object may have dropped early");

                // Release the object and let gravity complete the placement
                if (targetCube != null)
                {
                    yield return StartCoroutine(SettleCubeFlat());
                    targetCube = null;
                }

                // Wait for the object to settle in the container
                // (1.0 s gives the object time to reach the container floor)
                yield return new WaitForSeconds(1.0f);

                // Post-release check: bounding-box overlap with the container
                bool bboxOK = false;
                if (releasedObject != null)
                {
                    bboxOK = PerformBBoxOverlapCheck(releasedObject);
                    if (bboxOK)
                        Debug.Log($"[place check] object inside container '{lastBBoxContainerName}', overlap={lastBBoxOverlap:F2}");
                    else
                        Debug.LogWarning($"[place check] object not in container, overlap={lastBBoxOverlap:F2}, container='{lastBBoxContainerName}'");
                }
                else
                {
                    Debug.LogWarning("[place check] no object reference; check skipped");
                }

                yield return StartCoroutine(MoveToPos(hoverPos));

                if (bboxOK)
                {
                    Debug.Log("[place] placement verified");
                    SendStatusToPython(BuildPlaceSuccessJson());
                }
                else
                {
                    Debug.LogWarning("[place check] failed: bounding-box overlap below threshold");
                    SendStatusToPython(BuildPlaceFailedJson());
                }
            }
        }
        else if (upperAction.StartsWith("RESET_SCENE"))
        {
            Debug.Log("[reset] restoring initial object poses");
            yield return StartCoroutine(ResetScene());
        }
        else if (upperAction.StartsWith("LOAD_SCENE:"))
        {
            // Runtime scene change (used by the experiment scripts)
            string sceneName = originalAction.Substring("LOAD_SCENE:".Length).Trim();
            Debug.Log($"[scene] loading '{sceneName}'; the TCP port will be bound again");
            UnityEngine.SceneManagement.SceneManager.LoadScene(sceneName);
            yield break;
        }

        bool TryBlindGrasp(string targetName = "")
        {
            // Search around MognePoint, which marks the closed-fingertip centre
            Vector3 fingertipPos = gripperCenter.position;
            Collider[] colliders = Physics.OverlapSphere(fingertipPos, graspThreshold);

            // Candidates must have a Rigidbody; tables, floor, containers, IK targets and robot links are excluded
            var candidates = new List<(Collider col, float dist, string normalizedName)>();
            string hitObjects = "";
            foreach (var c in colliders)
            {
                hitObjects += c.name + ", ";

                string colName = c.name.ToUpper();
                if (c.transform.IsChildOf(this.transform) || colName.Contains("TABLE") || colName.Contains("PLATE") || colName.Contains("FLOOR") || colName.Contains("BOWL") || colName.Contains("BOX"))
                    continue;
                if (ikTarget != null && c.transform == ikTarget)
                    continue;

                Rigidbody rb = c.GetComponentInParent<Rigidbody>();
                if (rb == null)
                {
                    Debug.Log($"[physics filter] {c.name} has no Rigidbody; not graspable");
                    continue;
                }

                float dist = Vector3.Distance(fingertipPos, c.transform.position);
                candidates.Add((c, dist, NormalizeNameForMatch(c.name)));
            }
            Debug.Log($"[grasp probe] fingertip Y={fingertipPos.y:F3}, candidates within {graspThreshold} m: {(candidates.Count > 0 ? string.Join(", ", candidates.ConvertAll(x => $"{x.col.name}({x.dist:F3}m)")) : "none")}");

            var selection=GraspContract.Select(candidates.Select(x=>x.col),targetName,revisionExpectedPick,fingertipPos);
            DiagnosticSelection(targetName,candidates.Select(x=>x.col).ToArray(),selection.collider,selection.reason);
            if(selection.body==null)
            {revisionGraspFailure=selection.reason;return false;}
            revisionGraspFailure="";
            targetCube=selection.body.transform;
            AttachCubeToGripper();
            Debug.Log($"[grasp lock] {selection.body.name}; identity={selection.reason}; requested={targetName}");
            return true;
        }

        // Normalised object name for matching (no spaces or underscores, lower case)
        string NormalizeNameForMatch(string name)
        {
            return GraspContract.Normalize(name);
        }

        // Grasp retries: tolerance to position error and irregular shapes
        IEnumerator TryBlindGraspWithRetry(string targetName, Vector3 basePos)
        {
            // Attempt 1: commanded coordinates, standard search radius
            if (TryBlindGrasp(targetName))
            {
                Debug.Log("[grasp retry] first attempt succeeded");
                yield break;
            }
            Debug.Log("[grasp retry] attempt 1 failed; lowering the gripper");

            // Attempt 2: 2 cm lower (compensates depth error)
            Vector3 lowerPos = basePos + Vector3.down * 0.02f;
            yield return StartCoroutine(MoveToPos(lowerPos));
            if (TryBlindGrasp(targetName))
            {
                Debug.Log("[grasp retry] succeeded after lowering (dY=-0.02 m)");
                yield break;
            }
            Debug.Log("[grasp retry] attempt 2 failed; lowering again");

            // Attempt 3: another 2 cm lower (-4 cm in total)
            Vector3 lowerPos2 = lowerPos + Vector3.down * 0.02f;
            yield return StartCoroutine(MoveToPos(lowerPos2));
            if (TryBlindGrasp(targetName))
            {
                Debug.Log("[grasp retry] succeeded after second lowering (dY=-0.04 m)");
                yield break;
            }
            Debug.Log("[grasp retry] attempt 3 failed; widening the search radius");

            // Attempt 4: wider search radius
            float savedThreshold = graspThreshold;
            graspThreshold = savedThreshold * 2.0f;  // 0.12 -> 0.24
            Debug.Log($"[grasp retry] search radius {savedThreshold:F3} -> {graspThreshold:F3}");
            if (TryBlindGrasp(targetName))
            {
                Debug.Log("[grasp retry] succeeded with the wider radius");
                graspThreshold = savedThreshold;
                yield break;
            }

            // Attempts 5-8: XY offsets of +-3 cm in four directions
            graspThreshold = savedThreshold * 1.5f;  // keep expanded
            Vector3[] jitters = new Vector3[] {
                new Vector3( 0.03f, 0,  0),
                new Vector3(-0.03f, 0,  0),
                new Vector3( 0,     0,  0.03f),
                new Vector3( 0,     0, -0.03f),
            };
            foreach (Vector3 jitter in jitters)
            {
                Vector3 jitterPos = basePos + jitter;
                yield return StartCoroutine(MoveToPos(jitterPos));
                if (TryBlindGrasp(targetName))
                {
                    Debug.Log($"[grasp retry] succeeded after XY offset (offset={jitter:F3})");
                    graspThreshold = savedThreshold;
                    yield break;
                }
            }

            // All attempts failed; return to the commanded position
            graspThreshold = savedThreshold;
            yield return StartCoroutine(MoveToPos(basePos));
            Debug.LogWarning("[grasp retry] all 8 attempts failed");
            // The caller then sends GRASP_FAILED
        }

        void AttachCubeToGripper()
        {
            if (targetCube == null) return;

            Rigidbody rb = targetCube.GetComponent<Rigidbody>();
            if (rb == null)
            {
                Debug.LogError("[joint] target object has no Rigidbody; cannot attach a FixedJoint");
                return;
            }

            // Diagnostics: state on entry
            Vector3 entryPos = targetCube.position;
            Vector3 entryVel = rb.velocity;
            bool entryKinematic = rb.isKinematic;
            Debug.Log($"[diag entry] {targetCube.name} pos={entryPos:F4} vel={entryVel.magnitude:F4}m/s kinematic={entryKinematic} gripperCenter={gripperCenter.position:F4}");

            // Bounding-box-aware alignment: the object top is placed at the fingertips so that it does not
            // penetrate the gripper (aligning the pivot with gripperCenter embedded the object and caused
            // separation impulses). connectedAnchor is computed in the unit-scale proxy frame.
            Collider objCol = targetCube.GetComponent<Collider>();
            Vector3 targetPos = gripperCenter.position;
            Vector3 centerOffset = Vector3.zero;
            if (objCol != null)
            {
                centerOffset = objCol.bounds.center - targetCube.position;
                // Distance from the object top to its pivot = centerOffset.y + extents.y
                float topToPivot = centerOffset.y + objCol.bounds.extents.y;
                // Pivot placed topToPivot below gripperCenter, so the object top is at the fingertips
                targetPos.y = gripperCenter.position.y - topToPivot;
                targetPos.x = gripperCenter.position.x;
                targetPos.z = gripperCenter.position.z;
                Debug.Log($"[diag align] {targetCube.name} bounds.center={objCol.bounds.center:F4} extents={objCol.bounds.extents:F4} centerOffset={centerOffset:F4} topToPivot={topToPivot:F4}m; pivot {topToPivot:F4}m below the fingertips");
            }
            else
            {
                Debug.Log($"[diag align] {targetCube.name} has no collider; pivot aligned");
            }

            // Ignore robot-object collisions before moving the object
            Collider[] robotColliders = this.GetComponentsInChildren<Collider>();
            Collider[] targetColliders = targetCube.GetComponentsInChildren<Collider>();
            Debug.Log($"[diag colliders] robot: {robotColliders.Length}, object: {targetColliders.Length}");
            foreach (Collider rc in robotColliders)
            {
                if (rc == null) continue;
                foreach (Collider tc in targetColliders)
                {
                    if (tc == null) continue;
                    Physics.IgnoreCollision(rc, tc, true);
                }
            }
            // Check Physics.IgnoreCollision
            int ignoreFailCount = 0;
            string firstFailPair = "";
            foreach (Collider rc in robotColliders)
            {
                if (rc == null) continue;
                foreach (Collider tc in targetColliders)
                {
                    if (tc == null) continue;
                    if (!Physics.GetIgnoreCollision(rc, tc))
                    {
                        ignoreFailCount++;
                        if (string.IsNullOrEmpty(firstFailPair))
                            firstFailPair = $"{rc.name} <-> {tc.name}";
                    }
                }
            }
            if (ignoreFailCount > 0)
                Debug.LogError($"[diag] IgnoreCollision not in effect for {ignoreFailCount} collider pairs; first pair: {firstFailPair}");
            else
                Debug.Log($"[diag] IgnoreCollision in effect for all {robotColliders.Length * targetColliders.Length} pairs");

            // Make the Rigidbody kinematic before moving it; otherwise PhysX corrects the position in later
            // steps and fights the joint constraint.
            bool wasKinematic = rb.isKinematic;
            rb.isKinematic = true;
            rb.velocity = Vector3.zero;
            rb.angularVelocity = Vector3.zero;
            targetCube.position = targetPos;
            Debug.Log($"[attach] {targetCube.name} position {entryPos:F4} -> {targetPos:F4}, d={(targetPos-entryPos).magnitude:F4}m (kinematic={rb.isKinematic})");

            // Bounding-box overlap diagnostics
            // Merged bounds of the gripper colliders within about 10 cm of the fingertips
            if (objCol != null)
            {
                Bounds gripperLocalBounds = new Bounds(gripperCenter.position, Vector3.zero);
                int nearColCount = 0;
                foreach (Collider rc in robotColliders)
                {
                    if (rc == null) continue;
                    if (Vector3.Distance(rc.bounds.center, gripperCenter.position) < 0.12f)
                    {
                        gripperLocalBounds.Encapsulate(rc.bounds);
                        nearColCount++;
                    }
                }
                Bounds objBounds = objCol.bounds;
                bool overlaps = objBounds.Intersects(gripperLocalBounds);
                // Overlap depth
                float overlapY = 0f;
                if (overlaps)
                {
                    float minOverlap = Mathf.Min(objBounds.max.y, gripperLocalBounds.max.y);
                    float maxOverlap = Mathf.Max(objBounds.min.y, gripperLocalBounds.min.y);
                    overlapY = minOverlap - maxOverlap;
                }
                Debug.Log($"[bounds diag] gripper ({nearColCount} colliders) bounds=[{gripperLocalBounds.min:F4} ~ {gripperLocalBounds.max:F4}] size=[{gripperLocalBounds.size:F4}]");
                Debug.Log($"[bounds diag] object bounds=[{objBounds.min:F4} ~ {objBounds.max:F4}] size=[{objBounds.size:F4}]");
                Debug.Log($"[bounds diag] overlap={overlaps}, Y overlap depth={overlapY:F4}m, object top - gripper centre Y={objBounds.max.y - gripperCenter.position.y:F4}m");
            }

            // 1. Remove a leftover FixedJoint, if any
            FixedJoint existingJoint = targetCube.gameObject.GetComponent<FixedJoint>();
            if (existingJoint != null)
            {
                Debug.Log($"[diag joint] removing old joint, breakForce={existingJoint.breakForce}");
                Destroy(existingJoint);
            }

            // 2. Add a FixedJoint connected to the proxy anchor
            //
            // autoConfigureConnectedAnchor must be set to false before connectedBody; otherwise the anchor is
            // computed from the previous Rigidbody pose and the solver keeps an inconsistent state.
            FixedJoint joint = targetCube.gameObject.AddComponent<FixedJoint>();
            joint.autoConfigureConnectedAnchor = false; // must precede connectedBody
            joint.connectedBody = jointProxyRB;
            joint.breakForce = Mathf.Infinity;
            joint.breakTorque = Mathf.Infinity;
            joint.enableCollision = false;
            joint.enablePreprocessing = true;

            // The object pivot is at targetPos and the proxy at gripperCenter.
            // anchor (0,0,0) attaches the constraint at the object pivot;
            // connectedAnchor is the pivot position in the proxy frame.
            //
            // The proxy is a kinematic Rigidbody, so its Transform is authoritative: set the Transform first,
            // then call SyncTransforms to push it to the Rigidbody.
            jointProxyAnchor.transform.SetPositionAndRotation(gripperCenter.position, gripperCenter.rotation);
            Physics.SyncTransforms(); // Transform -> Rigidbody for the kinematic proxy
            Vector3 anchorInProxy = jointProxyAnchor.transform.InverseTransformPoint(targetPos);
            Debug.Log($"[diag anchor] proxyTf.pos=({jointProxyAnchor.transform.position.x:F4},{jointProxyAnchor.transform.position.y:F4},{jointProxyAnchor.transform.position.z:F4}) proxyRb.pos=({jointProxyRB.position.x:F4},{jointProxyRB.position.y:F4},{jointProxyRB.position.z:F4}) dPosRbTf={jointProxyRB.position - jointProxyAnchor.transform.position:F6} gripperCenter.rot=({gripperCenter.rotation.eulerAngles.x:F1},{gripperCenter.rotation.eulerAngles.y:F1},{gripperCenter.rotation.eulerAngles.z:F1}) proxyRb.rot=({jointProxyRB.rotation.eulerAngles.x:F1},{jointProxyRB.rotation.eulerAngles.y:F1},{jointProxyRB.rotation.eulerAngles.z:F1})");

            joint.anchor = Vector3.zero;
            joint.connectedAnchor = anchorInProxy;

            Debug.Log($"[diag anchor] object top at fingertips, anchor=(0,0,0) connectedAnchor={anchorInProxy:F4} proxyScale={jointProxyAnchor.transform.lossyScale:F4}");

            // 4. The object stays kinematic here; the caller makes it dynamic after the next physics step,
            // so that the joint is created with an exact anchor.
            rb.useGravity = true;
            // rb.isKinematic stays true for now; the caller will un-kinematic after WaitForFixedUpdate

            // Diagnostics: state on exit
            Debug.Log($"[diag exit] {targetCube.name} pos={targetCube.position:F4} vel={rb.velocity.magnitude:F4}m/s kinematic={rb.isKinematic} wasKinematic={wasKinematic} Joint.connectedBody={joint.connectedBody?.name ?? "NULL"}");
            Debug.Log($"[joint] FixedJoint attached: {targetCube.name} <-> gripperCenter, breakForce=infinite");

            // Grasp stability: for asymmetric or large objects the joint anchor lies topToPivot below the
            // fingertips while the centre of mass is at the geometric centre, so constraint force and gravity
            // form a couple when the object becomes dynamic. The centre of mass is therefore moved to the
            // anchor, angular drag is raised from 0.05 to 5.0, and the object colliders are disabled while
            // the grasp settles.
            if (!hasSavedPhysicsProps)
            {
                savedOriginalCenterOfMass = rb.centerOfMass;
                savedOriginalAngularDrag = rb.angularDrag;
                hasSavedPhysicsProps = true;
            }
            rb.centerOfMass = Vector3.zero;  // at the FixedJoint anchor: no constraint-gravity couple
            rb.angularDrag = 5f;  // raised from 0.05 to damp angular oscillation
            Debug.Log($"[stability] centre of mass at anchor (Vector3.zero), angularDrag 0.05 -> 5.0 " +
                      $"savedOrigCOM={savedOriginalCenterOfMass:F4} savedOrigAngDrag={savedOriginalAngularDrag:F3}");

            // Disable the target colliders while the grasp settles, so that the transient does not push
            // neighbouring objects; they are re-enabled before the lift test.
            if (targetColliders != null)
            {
                foreach (Collider tc in targetColliders)
                {
                    if (tc != null && tc.enabled)
                    {
                        _savedColliderStates[tc] = true;
                        tc.enabled = false;
                    }
                }
                Debug.Log($"[stability] disabled {_savedColliderStates.Count} target colliders while the grasp settles");
            }
            // Lock immediately when the grasp joint is established, before lifting.
            if (ikSolver != null) ikSolver.skipWristRotation = true;
            DiagnosticMark("attached_kinematic");
        }

        // Whether the FixedJoint is still valid (transport monitoring)
        bool IsStillHolding()
        {
            if (targetCube == null) return false;
            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
            return joint != null && joint.connectedBody != null;
        }

        // Re-enable the target colliders disabled during settling
        void RestoreTargetColliders()
        {
            if (_savedColliderStates.Count == 0) return;
            int restored = 0;
            foreach (var kv in _savedColliderStates)
            {
                if (kv.Key != null)
                {
                    kv.Key.enabled = kv.Value;  // saved state (usually true)
                    restored++;
                }
            }
            Debug.Log($"[stability] re-enabled {restored}/{_savedColliderStates.Count} target colliders");
            _savedColliderStates.Clear();
        }

        // Lift test: raise the gripper slowly, record contacts and lift height, compute GQS
        IEnumerator PerformLiftTest()
        {
            lastContactCount = 0;
            lastDeltaY = 0f;
            lastGQS = 0f;

            if (targetCube == null) yield break;

            // 0. Joint break threshold disabled during the lift test, which measures deltaY only;
            //    joint strength is relevant during transport.
            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
            float savedBreakForce = 0f;
            if (joint != null)
            {
                savedBreakForce = joint.breakForce;
                joint.breakForce = Mathf.Infinity;
            }

            // 0. Wait a few physics steps so that the joint solver converges after the object becomes dynamic
            yield return new WaitForSeconds(0.2f);

            // 1. Initial height of the bounding-box bottom (bounds.min.y, not the model pivot)
            Collider liftCol = targetCube.GetComponent<Collider>();
            float startBottomY = liftCol != null ? liftCol.bounds.min.y : targetCube.position.y;

            // 2. Contact count near the gripper
            Collider[] contacts = Physics.OverlapSphere(gripperCenter.position, graspThreshold * 1.5f);
            foreach (Collider c in contacts)
            {
                if (c.transform == targetCube || c.transform.IsChildOf(targetCube))
                    lastContactCount++;
            }
            lastContactCount = Mathf.Max(lastContactCount, 1); // the FixedJoint counts as one contact

            // 3. Raise ikTarget slowly (the IK solver moves the gripper, as in MoveTo)
            // Raise from the actual end-effector pose, not a nominal target that
            // the preceding approach may still miss by the shared 20 mm tolerance.
            Vector3 liftStart = gripperCenter.position;
            DiagnosticMark("lift_start");
            ikTarget.position = liftStart;
            Vector3 liftTarget = liftStart + Vector3.up * liftTestHeight;
            float t = 0f;
            float liftDuration = liftTestHeight / liftTestSpeed;

            while (t < liftDuration)
            {
                t += Time.deltaTime;

                // Detect a joint destroyed during the lift
                if (!IsStillHolding())
                {
                    Debug.LogWarning("[lift test] joint lost during the lift; grasp invalid");
                    lastDeltaY = 0f;
                    lastGQS = 0f;
                    // Restore the original breakForce (skipped if the joint no longer exists)
                    if (joint != null) joint.breakForce = savedBreakForce;
                    yield break;
                }

                ikTarget.position = Vector3.Lerp(liftStart, liftTarget, t / liftDuration);
                yield return null;
            }

            ikTarget.position = liftTarget;
            // E2 common primitive: observe lift only after bounded actual IK settling.
            // Keep the existing 0.8 * liftTestHeight acceptance threshold unchanged.
            float settleTime = 0f;
            while (Vector3.Distance(gripperCenter.position,liftTarget) > .005f && settleTime < 3f)
            {
                settleTime += Time.deltaTime;
                yield return null;
            }
            yield return new WaitForFixedUpdate();
            yield return new WaitForFixedUpdate();
            RecordRevisionMotion(liftTarget,t+settleTime);

            // 4. Lift height, with an 80% tolerance for elastic stretch
            if (targetCube != null && IsStillHolding())
            {
                // bounds.min.y measures the real bottom lift (joint stretch cannot pass the test through the pivot)
                Collider endCol = targetCube.GetComponent<Collider>();
                float currentBottomY = endCol != null ? endCol.bounds.min.y : targetCube.position.y;
                lastDeltaY = currentBottomY - startBottomY;
            }
            else
            {
                lastDeltaY = 0f;
            }

            DiagnosticMark("lift_end");
            // 5. GQS = contact_ratio x lift_ratio (both terms must be high)
            // contact_ratio = clamp(lastContactCount / requiredContactCount, 0, 1)
            // lift_ratio    = clamp(lastDeltaY / liftTestHeight, 0, 1)
            float contactRatio = Mathf.Clamp01((float)lastContactCount / requiredContactCount);
            float liftRatio = Mathf.Clamp01(lastDeltaY / liftTestHeight);
            lastGQS = contactRatio * liftRatio;

            // Diagnostics and the real decision share the unchanged 80% threshold.
            bool liftPassed = GraspContract.LiftPasses(lastDeltaY,liftTestHeight);

            Debug.Log($"[lift test] contacts={lastContactCount}/{requiredContactCount} " +
                      $"deltaY={lastDeltaY:F4}m (threshold={GraspContract.RequiredLift(liftTestHeight):F4}m) " +
                      $"GQS={lastGQS:F3} " +
                      $"-> {(liftPassed ? "passed" : "failed")}");

            // 6. Restore the original breakForce for transport
            if (joint != null) joint.breakForce = savedBreakForce;
        }


        // Diagnostics: per-frame monitoring after the object becomes dynamic
        // (called after AttachCubeToGripper and WaitForFixedUpdate; 10 FixedUpdate steps, about 0.2 s)
        IEnumerator DiagnosticPostKinematicMonitor()
        {
            if (targetCube == null) yield break;
            Rigidbody rb = targetCube.GetComponent<Rigidbody>();
            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
            Collider col = targetCube.GetComponent<Collider>();

            Debug.Log($"[frame monitor] {targetCube.name} after becoming dynamic");
            bool colEnabled = col != null ? col.enabled : false;
            Debug.Log($"  [frame 0] pos={targetCube.position:F4} vel={rb?.velocity.magnitude:F5}m/s angVel={rb?.angularVelocity.magnitude:F5} kinematic={rb?.isKinematic} colliderEnabled={colEnabled}");
            Debug.Log($"  [frame 0] gripperCenter={gripperCenter.position:F4} relative={targetCube.position - gripperCenter.position:F4}");
            if (joint != null)
                Debug.Log($"  [frame 0] autoConfigure={joint.autoConfigureConnectedAnchor} anchor={joint.anchor:F4} connectedAnchor={joint.connectedAnchor:F4}");

            float elapsed = 0f;
            for (int i = 0; i < 10; i++)
            {
                yield return new WaitForFixedUpdate();
                elapsed += Time.fixedDeltaTime;
                if (targetCube == null) break;
                rb = targetCube.GetComponent<Rigidbody>();
                joint = targetCube.GetComponent<FixedJoint>();
                col = targetCube.GetComponent<Collider>();

                Vector3 deltaFromGripper = targetCube.position - gripperCenter.position;
                float boundsCenterDist = col != null ? Vector3.Distance(col.bounds.center, gripperCenter.position) : -1f;
                string anchorInfo = joint != null
                    ? $"anchor={joint.anchor:F4} connAnchor={joint.connectedAnchor:F4} auto={joint.autoConfigureConnectedAnchor}"
                    : "Joint=NULL";

                Debug.Log($"  [frame {i+1}] t={elapsed:F3}s pos={targetCube.position:F4} dFromGrip={deltaFromGripper:F4} " +
                    $"vel={rb?.velocity.magnitude:F5}m/s angVel={rb?.angularVelocity.magnitude:F5} " +
                    $"boundsDist={boundsCenterDist:F4}m {anchorInfo}");
            }
            Debug.Log($"[frame monitor] done, {elapsed:F3}s");

            // Followed by the 5-frame velocity monitor for comparison
            yield return StartCoroutine(DiagnosticVelocityMonitor());
        }

        // Diagnostics: velocity monitor over 5 frames
        IEnumerator DiagnosticVelocityMonitor()
        {
            if (targetCube == null) yield break;
            Rigidbody rb = targetCube.GetComponent<Rigidbody>();
            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
            Collider col = targetCube.GetComponent<Collider>();

            Debug.Log($"[velocity monitor] 5 frames of {targetCube.name}");
            Debug.Log($"  [initial] pos={targetCube.position:F4} vel={rb?.velocity.magnitude:F5}m/s angVel={rb?.angularVelocity.magnitude:F5} kinematic={rb?.isKinematic} Joint={joint!=null} Joint.breakForce={joint?.breakForce}");
            if (col != null)
            {
                Debug.Log($"  [initial] bounds.center={col.bounds.center:F4} bounds.min={col.bounds.min:F4} bounds.max={col.bounds.max:F4}");
                Debug.Log($"  [initial] gripperCenter={gripperCenter.position:F4} object centre to gripper centre={Vector3.Distance(col.bounds.center, gripperCenter.position):F4}m");
            }

            for (int i = 0; i < 5; i++)
            {
                yield return null; // one frame
                if (targetCube == null) break;
                rb = targetCube.GetComponent<Rigidbody>();
                joint = targetCube.GetComponent<FixedJoint>();
                float distToGripper = Vector3.Distance(targetCube.position, gripperCenter.position);
                Debug.Log($"  [frame {i+1}] pos={targetCube.position:F4} vel={rb?.velocity.magnitude:F5}m/s angVel={rb?.angularVelocity.magnitude:F5} JointOk={joint!=null&&joint.connectedBody!=null} distToGripper={distToGripper:F4}m");
            }
            Debug.Log($"[velocity monitor] done");
        }

        // Release the object (destroy the FixedJoint)
        IEnumerator SettleCubeFlat()
        {
            if (targetCube == null) yield break;

            // Restore the target colliders on the release path
            RestoreTargetColliders();

            // Unlock the wrist on release
            if (ikSolver != null)
                ikSolver.skipWristRotation = false;

            // Restore robot-object collisions, which were ignored while the object was attached
            Collider[] robotColliders = this.GetComponentsInChildren<Collider>();
            Collider[] targetColliders = targetCube.GetComponentsInChildren<Collider>();
            foreach (Collider rc in robotColliders)
            {
                foreach (Collider tc in targetColliders)
                {
                    if (rc != null && tc != null)
                    {
                        Physics.IgnoreCollision(rc, tc, false);
                    }
                }
            }
            Debug.Log($"[collisions] robot <-> {targetCube.name} collisions restored");

            // 1. Destroy the FixedJoint; the object continues with its current pose and velocity
            Debug.Log($"[place diag release] gripperCenter=({gripperCenter.position.x:F4}, {gripperCenter.position.y:F4}, {gripperCenter.position.z:F4}) object pos=({targetCube.position.x:F4}, {targetCube.position.y:F4}, {targetCube.position.z:F4})");
            FixedJoint joint = targetCube.GetComponent<FixedJoint>();
            if (joint != null)
                Destroy(joint);

            Rigidbody rb = targetCube.GetComponent<Rigidbody>();
            if (rb != null)
            {
                // 2. Zero the velocity at release
                rb.velocity = Vector3.zero;
                rb.angularVelocity = Vector3.zero;

                // 3. Make sure the object is dynamic
                rb.isKinematic = false;
                rb.useGravity = true;
                rb.WakeUp();

                // 4. Landing stabiliser: strong angular drag (50) and a 1.0 s wait reduce bouncing and rolling
                float dropAngularDrag = rb.angularDrag;
                float originalDrag = rb.drag;
                rb.angularDrag = 50f;
                rb.drag = 8f;  // linear drag against bouncing

                yield return new WaitForSeconds(1.0f);

                // 5. Restore the original mass properties
                if (rb != null)
                {
                    rb.angularDrag = 0.05f;  // Unity default
                    rb.drag = originalDrag;

                    // The centre of mass was moved to the grasp point while attached and is restored here
                    if (hasSavedPhysicsProps)
                    {
                        rb.centerOfMass = savedOriginalCenterOfMass;
                        Debug.Log($"[stability] restored centerOfMass={savedOriginalCenterOfMass:F4} angularDrag=0.05");
                        hasSavedPhysicsProps = false;
                    }
                }
            }
            else
            {
                yield return new WaitForSeconds(1.0f);
            }
        }

        // Bounding-box check: overlap of the XZ projections of the object and container bounds
        bool PerformBBoxOverlapCheck(Transform heldObject)
        {
            lastBBoxOverlap = 0f;
            lastBBoxContainerName = "";

            if (heldObject == null) return false;

            Collider objCol = heldObject.GetComponent<Collider>();
            if (objCol == null)
            {
                Debug.LogWarning("[bounds check] object has no collider; overlap not computed");
                return false;
            }

            Bounds objBounds = objCol.bounds;

            // Object XZ rectangle
            float objMinX = objBounds.min.x;
            float objMaxX = objBounds.max.x;
            float objMinZ = objBounds.min.z;
            float objMaxZ = objBounds.max.z;
            float objArea = (objMaxX - objMinX) * (objMaxZ - objMinZ);

            if (objArea <= 0f)
            {
                Debug.LogWarning("[bounds check] object XZ area is zero");
                return false;
            }

            // Raycast down from the object bounds centre to find the container
            Vector3 rayOrigin = objBounds.center;
            RaycastHit hit;
            if (!Physics.Raycast(rayOrigin, Vector3.down, out hit, 0.5f))
            {
                Debug.LogWarning("[bounds check] no surface below the object");
                return false;
            }

            string hitName = hit.collider.name.ToUpper();
            if (!(hitName.Contains("PLATE") || hitName.Contains("BOWL") || hitName.Contains("BOX") ||
                  hitName.Contains("CONTAINER") || hitName.Contains("DISH") || hitName.Contains("TRAY") || hitName.Contains("CUP")))
            {
                Debug.LogWarning($"[bounds check] '{hit.collider.name}' below the object is not a container");
                return false;
            }

            lastBBoxContainerName = hit.collider.name;

            // Container XZ rectangle
            Bounds contBounds = hit.collider.bounds;
            float contMinX = contBounds.min.x;
            float contMaxX = contBounds.max.x;
            float contMinZ = contBounds.min.z;
            float contMaxZ = contBounds.max.z;

            // Intersection area in the XZ plane
            float ixMin = Mathf.Max(objMinX, contMinX);
            float ixMax = Mathf.Min(objMaxX, contMaxX);
            float izMin = Mathf.Max(objMinZ, contMinZ);
            float izMax = Mathf.Min(objMaxZ, contMaxZ);

            float interArea = Mathf.Max(0f, ixMax - ixMin) * Mathf.Max(0f, izMax - izMin);
            lastBBoxOverlap = interArea / objArea;

            Debug.Log($"[bounds check] object XZ=[{objMinX:F3}~{objMaxX:F3}]x[{objMinZ:F3}~{objMaxZ:F3}] area={objArea:F4}m2");
            Debug.Log($"[bounds check] container XZ=[{contMinX:F3}~{contMaxX:F3}]x[{contMinZ:F3}~{contMaxZ:F3}] intersection={interArea:F4}m2");
            Debug.Log($"[bounds check] overlap={lastBBoxOverlap:F3} (threshold 0.50) -> {(lastBBoxOverlap >= 0.50f ? "passed" : "failed")}");

            return lastBBoxOverlap >= 0.50f;
        }

        // ================================================================
        // Disturbance injection, triggered by a DISTURB: command from the Python side
        // ================================================================

        IEnumerator ExecuteDisturbance(string command)
        {
            // Types: "pre_grasp_offset:RedCube" / "mid_transport_drop" / "container_shift:bowl02"
            string[] parts = command.Split(':');
            string disturbType = parts[0].Trim().ToLower();
            string targetName = parts.Length >= 2 ? parts[1].Trim() : "";

            switch (disturbType)
            {
                case "pre_grasp_offset":
                    ApplyPreGraspOffset(targetName);
                    break;
                case "mid_transport_drop":
                    ApplyMidTransportDrop();
                    break;
                case "container_shift":
                    ApplyContainerShift(targetName);
                    break;
                default:
                    Debug.LogWarning($"[disturbance] unknown type '{disturbType}' (supported: pre_grasp_offset, mid_transport_drop, container_shift)");
                    yield break;
            }

            yield return new WaitForSeconds(0.3f); // let physics settle
            Debug.Log($"[disturbance] '{disturbType}' done");
        }

        // Disturbance 1: random offset of an object before the grasp
        void ApplyPreGraspOffset(string objectName)
        {
            if (string.IsNullOrEmpty(objectName)) return;

            GameObject obj = GameObject.Find(objectName);
            if (obj == null)
            {
                // Case-insensitive fallback lookup
                foreach (GameObject go in FindObjectsOfType<GameObject>())
                {
                    if (go.name.Equals(objectName, StringComparison.OrdinalIgnoreCase))
                    { obj = go; break; }
                }
            }
            if (obj == null)
            {
                Debug.LogWarning($"[disturbance] object '{objectName}' not found");
                return;
            }

            Vector3 offset = new Vector3(
                UnityEngine.Random.Range(-preGraspOffsetRange, preGraspOffsetRange),
                0,
                UnityEngine.Random.Range(-preGraspOffsetRange, preGraspOffsetRange));
            obj.transform.position += offset;

            Debug.Log($"[disturbance] pre_grasp_offset: '{objectName}' moved {offset.magnitude:F3}m");
        }

        // Disturbance 2: drop during transport (impulse above the joint breakForce)
        void ApplyMidTransportDrop()
        {
            if (targetCube == null)
            {
                Debug.LogWarning("[disturbance] no object held; mid_transport_drop skipped");
                return;
            }

            Rigidbody rb = targetCube.GetComponent<Rigidbody>();
            if (rb != null)
            {
                rb.AddForce(Vector3.down * midTransportDropForce, ForceMode.Impulse);
                Debug.Log($"[disturbance] mid_transport_drop: '{targetCube.name}' impulse {midTransportDropForce}N downwards; joint expected to break");
            }
        }

        // Disturbance 3: random shift of a container before placement
        void ApplyContainerShift(string containerName)
        {
            if (string.IsNullOrEmpty(containerName)) return;

            GameObject container = GameObject.Find(containerName);
            if (container == null)
            {
                foreach (GameObject go in FindObjectsOfType<GameObject>())
                {
                    if (go.name.Equals(containerName, StringComparison.OrdinalIgnoreCase))
                    { container = go; break; }
                }
            }
            if (container == null)
            {
                Debug.LogWarning($"[disturbance] container '{containerName}' not found");
                return;
            }

            Vector3 shift = new Vector3(
                UnityEngine.Random.Range(-containerShiftRange, containerShiftRange),
                0,
                UnityEngine.Random.Range(-containerShiftRange, containerShiftRange));
            container.transform.position += shift;

            Debug.Log($"[disturbance] container_shift: '{containerName}' moved {shift.magnitude:F3}m");
        }

        // Scene reset: restore all objects to their initial poses
        IEnumerator ResetScene()
        {
            // 1. Release the held object and restore its mass properties
            if (targetCube != null)
            {
                Rigidbody heldRb = targetCube.GetComponent<Rigidbody>();
                if (heldRb != null && hasSavedPhysicsProps)
                {
                    heldRb.centerOfMass = savedOriginalCenterOfMass;
                    heldRb.angularDrag = savedOriginalAngularDrag;
                    hasSavedPhysicsProps = false;
                }
                // Restore the target colliders on the reset path
                RestoreTargetColliders();
                // Unlock the wrist
                if (ikSolver != null)
                    ikSolver.skipWristRotation = false;
                FixedJoint joint = targetCube.GetComponent<FixedJoint>();
                if (joint != null) Destroy(joint);
                targetCube = null;
            }

            // 2. Restore the recorded initial poses
            foreach (var kvp in initialPoses)
            {
                GameObject obj = kvp.Key;
                if (obj == null) continue;

                Rigidbody rb = obj.GetComponent<Rigidbody>();
                if (rb != null)
                {
                    rb.velocity = Vector3.zero;
                    rb.angularVelocity = Vector3.zero;
                    rb.isKinematic = true;
                }

                obj.transform.position = kvp.Value.pos;
                obj.transform.rotation = kvp.Value.rot;

                if (rb != null)
                {
                    rb.isKinematic = false;
                    rb.WakeUp();
                }
            }

            // 3. Clear the verification cache
            lastContactCount = 0;
            lastDeltaY = 0f;
            lastGQS = 0f;
            lastBBoxOverlap = 0f;
            lastBBoxContainerName = "";

            // 4. Reset the Unity random number generator for reproducibility
            UnityEngine.Random.InitState(42);

            yield return new WaitForSeconds(0.5f); // let physics settle
            Debug.Log("[reset] all objects restored to their initial poses");
            SendStatusToPython("STATUS:SCENE_RESET|{}");
        }

        IEnumerator MoveTo(Vector3 pos, bool monitorGrasp = false)
        {
            float timer = 0f;
            float timeout = 20f;

            while ((Vector3.Distance(ikTarget.position, pos) > 0.02f ||
                    Vector3.Distance(gripperCenter.position, pos) > 0.02f) && timer < timeout)
            {
                timer += Time.deltaTime;

                if (monitorGrasp && !IsStillHolding())
                {
                    Debug.LogWarning("[transport] FixedJoint broken; the object dropped");
                    yield break;
                }

                if (robotBaseYawNode != null)
                {
                    Vector3 targetDirection = pos - robotBaseYawNode.position;
                    targetDirection.y = 0;
                    if (targetDirection.sqrMagnitude > 0.001f)
                    {
                        Quaternion targetRotation = Quaternion.LookRotation(targetDirection);
                        robotBaseYawNode.rotation = Quaternion.RotateTowards(robotBaseYawNode.rotation, targetRotation, baseRotationSpeed * Time.deltaTime);
                    }
                }

                ikTarget.position = Vector3.MoveTowards(ikTarget.position, pos, moveSpeed * Time.deltaTime);
                yield return null;
            }
            RecordRevisionMotion(pos,timer);
        }

        IEnumerator MoveToPos(Vector3 currentTargetPos, bool monitorGrasp = false)
        {
            yield return StartCoroutine(MoveTo(currentTargetPos, monitorGrasp));
        }

        IEnumerator CaptureAndSendImage()
        {
            if (cameraMain == null || cameraAux == null) yield break;

            cameraMain.depthTextureMode = DepthTextureMode.Depth;
            cameraAux.depthTextureMode = DepthTextureMode.Depth;
            yield return new WaitForEndOfFrame();

            Shader depthShader = Shader.Find("Custom/DepthToGrayscale");
            string mainRgb, mainDepth, sideRgb, sideDepth;
            CaptureCameraStream(cameraMain, depthShader, out mainRgb, out mainDepth);
            CaptureCameraStream(cameraAux, depthShader, out sideRgb, out sideDepth);

            string message = "MULTI_RGBD:" + mainRgb + "|" + mainDepth + "|" + sideRgb + "|" + sideDepth;
            SendStatusToPython(message);
        }
    }

    private void CaptureCameraStream(Camera cam, Shader depthShader, out string rgbBase64, out string depthBase64)
    {
        RenderTexture rtRGB = new RenderTexture(512, 512, 24);
        cam.targetTexture = rtRGB;
        cam.Render();
        RenderTexture.active = rtRGB;
        Texture2D texRGB = new Texture2D(512, 512, TextureFormat.RGB24, false);
        texRGB.ReadPixels(new Rect(0, 0, 512, 512), 0, 0);
        texRGB.Apply();

        RenderTexture rtDepth = new RenderTexture(512, 512, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
        cam.targetTexture = rtDepth;
        if (depthShader != null) cam.RenderWithShader(depthShader, "");
        RenderTexture.active = rtDepth;

        Texture2D texDepth = new Texture2D(512, 512, TextureFormat.RGB24, false, true);
        texDepth.ReadPixels(new Rect(0, 0, 512, 512), 0, 0);
        texDepth.Apply();

        cam.targetTexture = null;
        RenderTexture.active = null;

        rgbBase64 = Convert.ToBase64String(texRGB.EncodeToJPG(80));
        depthBase64 = Convert.ToBase64String(texDepth.EncodeToPNG());

        Destroy(rtRGB); Destroy(texRGB);
        Destroy(rtDepth); Destroy(texDepth);
    }

    // ================================================================
    // JSON status messages
    // ================================================================

    string BuildGraspSuccessJson()
    {
        // Format: STATUS:GRASP_SUCCESS|{"contact_count":3,"delta_y":0.048,"gqs":0.87,"method":"lift_test"}
        // Built by concatenation with InvariantCulture to avoid composite-format parsing issues in Mono
        string json = "{\"contact_count\":" + lastContactCount
            + ",\"delta_y\":" + lastDeltaY.ToString("F4", CultureInfo.InvariantCulture)
            + ",\"gqs\":" + lastGQS.ToString("F3", CultureInfo.InvariantCulture)
            + ",\"required_lift\":" + GraspContract.RequiredLift(liftTestHeight).ToString("F4", CultureInfo.InvariantCulture)
            + ",\"method\":\"lift_test\"}";
        return "STATUS:GRASP_SUCCESS|" + json;
    }

    string BuildGraspFailedJson()
    {
        // Format: STATUS:GRASP_FAILED|{"contact_count":0,"delta_y":0.0,"gqs":0.0,"method":"lift_test"}
        string json = "{\"contact_count\":" + lastContactCount
            + ",\"delta_y\":" + lastDeltaY.ToString("F4", CultureInfo.InvariantCulture)
            + ",\"gqs\":" + lastGQS.ToString("F3", CultureInfo.InvariantCulture)
            + ",\"required_lift\":" + GraspContract.RequiredLift(liftTestHeight).ToString("F4", CultureInfo.InvariantCulture)
            + ",\"reason\":\"" + revisionGraspFailure + "\",\"method\":\"lift_test\"}";
        return "STATUS:GRASP_FAILED|" + json;
    }

    string BuildPlaceSuccessJson()
    {
        // Format: STATUS:PLACE_SUCCESS|{"bbox_overlap":0.85,"container":"bowl02","method":"bbox_overlap"}
        string json = "{\"bbox_overlap\":" + lastBBoxOverlap.ToString("F3", CultureInfo.InvariantCulture)
            + ",\"container\":\"" + lastBBoxContainerName + "\""
            + ",\"method\":\"bbox_overlap\"}";
        return "STATUS:PLACE_SUCCESS|" + json;
    }

    string BuildPlaceFailedJson()
    {
        // Format: STATUS:PLACE_FAILED|{"bbox_overlap":0.23,"container":"bowl02","method":"bbox_overlap"}
        string json = "{\"bbox_overlap\":" + lastBBoxOverlap.ToString("F3", CultureInfo.InvariantCulture)
            + ",\"container\":\"" + lastBBoxContainerName + "\""
            + ",\"method\":\"bbox_overlap\"}";
        return "STATUS:PLACE_FAILED|" + json;
    }

    void SendStatusToPython(string message)
    {
        if (revisionPrimitiveStatus != null) { revisionPrimitiveStatus(message); return; }
        new Thread(() => {
            try
            {
                using (TcpClient client = new TcpClient(pythonServerIP, pythonServerPort))
                using (NetworkStream stream = client.GetStream())
                {
                    byte[] data = Encoding.UTF8.GetBytes(message);
                    stream.Write(data, 0, data.Length);
                    Thread.Sleep(50);
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"[communication]\nerror: {e.Message}");
            }
        }).Start();
    }
}
