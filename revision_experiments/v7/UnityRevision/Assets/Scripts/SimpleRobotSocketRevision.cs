using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using UnityEngine;
using PaperRevision;

// Isolated revision copy. Offline scores never enter the action controller.
public partial class SimpleRobotSocket
{
    public int revisionCommandPort=5505, revisionFeedbackPort=5506;
    [NonSerialized] public Action<string> revisionResponseSink;
    private Action<string> revisionPrimitiveStatus;
    private bool revisionBusy;
    private Dictionary<Transform,Vector3> revisionContainerPositions=new Dictionary<Transform,Vector3>();
    private Dictionary<Transform,Quaternion> revisionJointRotations=new Dictionary<Transform,Quaternion>();
    private Vector3 revisionInitialTargetPosition;
    private Quaternion revisionInitialTargetRotation;
    private List<MotionRecord> revisionMotions=new List<MotionRecord>();
    void SaveRevisionContainers()
    {
        SaveMechanismPhysics();
        foreach(Transform t in FindObjectsOfType<Transform>())
            if(t.name=="bowl02"||t.name=="plate02")revisionContainerPositions[t]=t.position;
        if(ikSolver!=null)foreach(var joint in ikSolver.joints)
            if(joint.bone!=null)revisionJointRotations[joint.bone]=joint.bone.localRotation;
        if(robotBaseYawNode!=null)revisionJointRotations[robotBaseYawNode]=robotBaseYawNode.localRotation;
        if(wristBone!=null)revisionJointRotations[wristBone]=wristBone.localRotation;
        if(ikTarget!=null){revisionInitialTargetPosition=ikTarget.position;revisionInitialTargetRotation=ikTarget.rotation;}
    }
    [Serializable] public class LayoutOffset { public string id; public Vector3 offset; }
    [Serializable] public class RevisionRequest
    {
        public string requestId,trialId,eventId,anchor,action,target,recoveryCondition;
        public Configuration configuration;
        public Vector3 position;
        public int seed;
        public LayoutOffset[] offsets;
    }
    [Serializable] public class HoldingFeedback
    { public string channel="controller_feedback",state="EMPTY",objectId,reason; public float jointGap; }
    [Serializable] public class CameraInfo { public Vector3 position,rotation; public float fov; }
    [Serializable] public class CameraImages
    { public string mainRgb,mainDepth,sideRgb,sideDepth; public CameraInfo mainCamera; }
    [Serializable] public class MotionRecord
    { public Vector3 target,actual; public float error,seconds; public bool converged; }
    [Serializable] public class PoseRecord
    { public string id; public Vector3 position,rotation; public bool hasRigidbody; public BodyObservation body; }
    [Serializable] public class RevisionResponse
    {
        public string requestId,error,primitiveStatus;
        public string[] primitiveMessages;
        public bool ok;
        public ScoreSnapshot score;
        public FaultRecord[] faults;
        public HoldingFeedback holding;
        public CameraImages images;
        public MotionRecord[] motions;
        public PoseRecord[] initialState;
        public ControlledLocation location;
        public DiagnosticTrace diagnostics;
        public WatchSnapshot watchdog;
    }
    void RecordRevisionMotion(Vector3 target,float seconds)
    {
        float error=gripperCenter==null?float.MaxValue:Vector3.Distance(gripperCenter.position,target);
        revisionMotions.Add(new MotionRecord{target=target,actual=gripperCenter.position,error=error,seconds=seconds,converged=error<=.02f});
    }
    HoldingFeedback RevisionHolding(RevisionRuntime runtime)
    {
        var feedback=new HoldingFeedback();
        if(targetCube==null)return feedback;
        FixedJoint joint=targetCube.GetComponent<FixedJoint>();
        if(joint==null||joint.connectedBody==null)return feedback;
        Entity owner=runtime.registry.FindOwner(targetCube);
        if(owner==null){feedback.state="UNKNOWN";return feedback;}
        feedback.jointGap=Vector3.Distance(joint.transform.TransformPoint(joint.anchor),
            joint.connectedBody.transform.TransformPoint(joint.connectedAnchor));
        if(float.IsNaN(feedback.jointGap)||float.IsInfinity(feedback.jointGap)||feedback.jointGap>.03f)
        {feedback.state="UNKNOWN";feedback.reason="joint_anchor_separation";feedback.objectId=owner.spec.id;return feedback;}
        feedback.state="HOLDING";feedback.objectId=owner.spec.id;return feedback;
    }
    CameraImages RevisionCapture()
    {
        if(cameraMain==null||cameraAux==null)throw new InvalidOperationException("Camera references missing");
        Shader shader=Shader.Find("Custom/DepthToGrayscale");
        if(shader==null)throw new InvalidOperationException("Depth shader missing");
        cameraMain.depthTextureMode=DepthTextureMode.Depth;cameraAux.depthTextureMode=DepthTextureMode.Depth;
        var frames=new CameraImages();
        // Explicit Camera.Render works in Editor batch mode; WaitForEndOfFrame does not.
        CaptureCameraStream(cameraMain,shader,out frames.mainRgb,out frames.mainDepth);
        CaptureCameraStream(cameraAux,shader,out frames.sideRgb,out frames.sideDepth);
        frames.mainCamera=new CameraInfo{position=cameraMain.transform.position,
            rotation=cameraMain.transform.eulerAngles,fov=cameraMain.fieldOfView};
        return frames;
    }
    IEnumerator RevisionPrimitive(string command,RevisionResponse response)
    {
        var messages=new List<string>();revisionPrimitiveStatus=messages.Add;revisionMotions.Clear();
        originalAction=command;
        yield return StartCoroutine(ProcessCommand(command.ToUpperInvariant()));
        revisionPrimitiveStatus=null;
        response.primitiveMessages=messages.ToArray();
        response.primitiveStatus=messages.LastOrDefault(m=>m.StartsWith("STATUS:"));
        response.motions=revisionMotions.ToArray();
        response.diagnostics=EndDiagnostic();
        revisionExpectedPick=null;
        if(revisionMotions.Any(m=>!m.converged))response.primitiveStatus="STATUS:MOTION_FAILED|{}";
    }
    IEnumerator RevisionReset(RevisionResponse response)
    {
        if(ikSolver!=null){ikSolver.isIkActive=false;ikSolver.skipWristRotation=false;}
        foreach(var pair in revisionJointRotations)if(pair.Key!=null)pair.Key.localRotation=pair.Value;
        if(ikTarget!=null){ikTarget.position=revisionInitialTargetPosition;ikTarget.rotation=revisionInitialTargetRotation;}
        yield return StartCoroutine(RevisionPrimitive("RESET_SCENE",response));
        RestoreMechanismPhysics();
        if(ikSolver!=null)ikSolver.isIkActive=false;
        foreach(var pair in revisionJointRotations)if(pair.Key!=null)pair.Key.localRotation=pair.Value;
        if(ikTarget!=null){ikTarget.position=revisionInitialTargetPosition;ikTarget.rotation=revisionInitialTargetRotation;}
        foreach(var pair in revisionContainerPositions)if(pair.Key!=null)pair.Key.position=pair.Value;
        Physics.SyncTransforms();yield return new WaitForSeconds(.5f);
    }
    IEnumerator RevisionQuit()
    {
        yield return new WaitForSeconds(.5f);
        #if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(0);
        #endif
    }
    IEnumerator ExecuteRevisionCommand(string command)
    {
        var response=new RevisionResponse();var runtime=GetComponent<RevisionRuntime>();
        IEnumerator operation=null;bool endTrial=false,quit=false,ownsBusy=false;
        try
        {
            int split=command.IndexOf(':');if(split<0)throw new ArgumentException("Missing payload");
            string verb=command.Substring(0,split).ToUpperInvariant();
            var request=JsonUtility.FromJson<RevisionRequest>(command.Substring(split+1));
            response.requestId=request.requestId;
            if(string.IsNullOrWhiteSpace(request.requestId))throw new ArgumentException("Missing requestId");
            if(verb=="REV_ABORT")
            {
                StopAllCoroutines();revisionPrimitiveStatus=null;revisionBusy=false;
                if(ikSolver!=null)ikSolver.isIkActive=false;
            }
            else
            {
                if(revisionBusy)throw new InvalidOperationException("Command already in progress");
                revisionBusy=true;ownsBusy=true;
                if(verb=="REV_PING") { }
                else if(verb=="REV_QUIT")
                {
                    if(!Environment.GetCommandLineArgs().Contains("-revisionRobot"))throw new InvalidOperationException("Not a revision robot process");
                    quit=true;
                }
                else if(verb=="REV_RESET")
                {
                    if(runtime!=null&&runtime.configuration!=null)throw new InvalidOperationException("End trial before reset");
                    operation=RevisionReset(response);
                }
                else if(verb=="REV_CONFIG")
                {
                    ConfigureMechanism(request);
                    if(runtime==null)runtime=gameObject.AddComponent<RevisionRuntime>();
                    runtime.Configure(request.configuration,spec=>{
                        var matches=FindObjectsOfType<Transform>().Where(t=>t.name==spec.sceneName).ToArray();
                        if(matches.Length!=1)throw new ArgumentException("Scene name must resolve uniquely: "+spec.sceneName);
                        return matches[0].gameObject;
                    });
                    foreach(var entry in request.offsets??new LayoutOffset[0])
                        runtime.registry.Resolve(entry.id,"object").obj.transform.position+=entry.offset;
                    Physics.SyncTransforms();
                    UnityEngine.Random.InitState(request.seed);
                    response.initialState=RevisionPoses(runtime);
                }
                else
                {
                    if(runtime==null||runtime.configuration==null)throw new InvalidOperationException("REV_CONFIG required");
                    if(request.trialId!=runtime.configuration.trialId)throw new ArgumentException("Trial ID mismatch");
                    if(verb=="REV_SCORE")response.score=runtime.Sample(Time.fixedTime);
                    else if(verb=="REV_LOCATE")response.location=ControlledLocate(runtime,request);
                    else if(verb=="REV_POSES")response.initialState=RevisionPoses(runtime);
                    else if(verb=="REV_WATCH_GOALS")response.watchdog=ObserveCompletion(runtime);
                    else if(verb=="REV_OBSERVE_AUDIT")
                    {
                        // Same main-thread instant, with no yield or physics step between reads.
                        // Watchdog/holding remain the only online inputs; score is audit-only.
                        response.holding=RevisionHolding(runtime);
                        response.watchdog=ObserveCompletion(runtime);
                        response.score=runtime.Sample(Time.fixedTime);
                    }
                    else if(verb=="REV_DIAGNOSTIC_WINDOW")operation=DiagnosticWindow(response);
                    else if(verb=="REV_ACK_LOSS")
                    {
                        if(!runtime.faultRecords.Any(f=>f.applied&&f.observedEffect)||RevisionHolding(runtime).state!="EMPTY")
                            throw new InvalidOperationException("Effective loss and empty gripper required");
                        AcknowledgeMechanismLoss();response.initialState=RevisionPoses(runtime);
                    }
                    else if(verb=="REV_RECOVERY_RESET")
                    {
                        if(revisionMechanismCondition!="reset_restart")throw new InvalidOperationException("Recovery reset forbidden for this condition");
                        if(revisionRecoveryResetUsed||!runtime.faultRecords.Any(f=>f.applied&&f.observedEffect))
                            throw new InvalidOperationException("One recovery reset only, after an effective scheduled fault");
                        revisionRecoveryResetUsed=true;
                        operation=MechanismRecoveryReset(runtime,response);
                    }
                    else if(verb=="REV_HOLD")response.holding=RevisionHolding(runtime);
                    else if(verb=="REV_CAPTURE")response.images=RevisionCapture();
                    else if(verb=="REV_DISTURB")operation=runtime.Inject(request.eventId,request.anchor,targetCube);
                    else if(verb=="REV_ACTION")
                    {
                        if(request.action!="PICK"&&request.action!="PLACE")throw new ArgumentException("Unknown action");
                        var diagnosticEntity=runtime.registry.Resolve(request.target,request.action=="PICK"?"object":"container");
                        Vector3 p=request.position;
                        if(float.IsNaN(p.sqrMagnitude)||float.IsInfinity(p.sqrMagnitude))throw new ArgumentException("Invalid coordinates");
                        string primitive="BLIND_"+request.action+":"+p.x.ToString("R",CultureInfo.InvariantCulture)+","+
                            p.y.ToString("R",CultureInfo.InvariantCulture)+","+p.z.ToString("R",CultureInfo.InvariantCulture)+"|"+request.target.Replace('_',' ');
                        BeginDiagnostic(request.action,diagnosticEntity.spec.id,diagnosticEntity.obj.transform);
                        revisionExpectedPick=request.action=="PICK"?diagnosticEntity.obj.transform:null;
                        operation=RevisionPrimitive(primitive,response);
                    }
                    else if(verb=="REV_END"){response.score=runtime.Sample(Time.fixedTime);endTrial=true;}
                    else if(verb!="REV_EVENTS")throw new ArgumentException("Unknown revision command");
                }
            }
            response.ok=true;
        }
        catch(Exception ex){response.ok=false;response.error=ex.Message;}
        if(operation!=null)
        {
            while(true)
            {
                bool next=false;object current=null;
                try{next=operation.MoveNext();if(next)current=operation.Current;}
                catch(Exception ex){response.ok=false;response.error=ex.Message;revisionPrimitiveStatus=null;}
                if(!next)break;yield return current;
            }
        }
        if(runtime!=null)response.faults=runtime.faultRecords.ToArray();
        if(ownsBusy)revisionBusy=false;
        string payload="REVISION:"+JsonUtility.ToJson(response);
        if(revisionResponseSink!=null)revisionResponseSink(payload);else SendStatusToPython(payload);
        if(endTrial&&response.ok){runtime.enabled=false;Destroy(runtime);}
        if(quit&&response.ok)StartCoroutine(RevisionQuit());
    }
}
