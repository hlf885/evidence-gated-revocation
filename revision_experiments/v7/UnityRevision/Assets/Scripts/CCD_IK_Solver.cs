using UnityEngine;
using System.Collections.Generic;

[System.Serializable]
public class IKJoint
{
    public Transform bone;
    [Tooltip("Local rotation axis, e.g. (1,0,0) for a pitch joint")]
    public Vector3 rotationAxis = new Vector3(1, 0, 0);
    [Range(0, 1)]
    public float orientationInfluence = 0f;
}

public class CCD_IK_Solver : MonoBehaviour
{
    [Header("Joints")]
    public List<IKJoint> joints = new List<IKJoint>();
    public Transform target;       // IK target (position and desired orientation)
    public Transform endEffector;  // end effector (gripper centre)

    [Header("Solver")]
    public int iterations = 15;
    public float delta = 0.001f;
    [Range(0, 1)]
    public float damping = 0.8f;

    [Header("Orientation constraint")]
    [Tooltip("End-effector axis that defines the grasp direction, usually transform.up or transform.forward")]
    public Vector3 endEffectorApproachAxis = Vector3.up;
    [Tooltip("Target axis that defines the desired grasp direction, usually transform.up")]
    public Vector3 targetApproachAxis = Vector3.up;
    [Tooltip("Distance below which the orientation constraint is applied (m)")]
    public float adaptiveThreshold = 0.15f;

    [Header("State")]
    public bool isIkActive = false;

    [Header("Wrist lock")]
    public Transform wristBone;           // wrist joint, set by SimpleRobotSocket.Start()
    public bool skipWristRotation = false; // true: the wrist is skipped and shoulder/elbow track the target

    void Update()
    {
        if (isIkActive && target != null && endEffector != null)
        {
            SolveIK();
        }
    }

    void SolveIK()
    {
        for (int i = 0; i < iterations; i++)
        {
            // Position error check
            float distError = Vector3.Distance(endEffector.position, target.position);
            if (distError < delta)
                break;

            // Cyclic coordinate descent from the end effector backwards
            // hand_link (fine), elbow_link (medium) and arm_link (coarse); the wrist is skipped while
            // skipWristRotation is set, so that held objects are not disturbed
            for (int j = joints.Count - 1; j >= 0; j--)
            {
                if (skipWristRotation && wristBone != null && joints[j].bone == wristBone)
                    continue;  // wrist skipped; shoulder and elbow compensate
                RotateJointConstrained(joints[j], distError);
            }
        }
    }

    // distError drives the adaptive weighting
    void RotateJointConstrained(IKJoint jointData, float currentDistance)
    {
        if (jointData.bone == null) return;

        Transform joint = jointData.bone;
        Vector3 axis = jointData.rotationAxis.normalized;

        // Step 1: position error term
        Vector3 localTargetPos = joint.InverseTransformPoint(target.position);
        Vector3 localEndPos = joint.InverseTransformPoint(endEffector.position);

        // Project onto the plane orthogonal to the rotation axis
        localTargetPos -= Vector3.Project(localTargetPos, axis);
        localEndPos -= Vector3.Project(localEndPos, axis);

        float theta_pos = 0f;
        // Tolerance near the origin avoids NaN and stalls
        if (localTargetPos.sqrMagnitude > 0.0001f && localEndPos.sqrMagnitude > 0.0001f)
        {
            // Signed angle from Atan2 of cross and dot products (more stable than Vector3.SignedAngle for short vectors)
            localTargetPos.Normalize();
            localEndPos.Normalize();
            float dot = Vector3.Dot(localEndPos, localTargetPos);
            float det = Vector3.Dot(axis, Vector3.Cross(localEndPos, localTargetPos));
            theta_pos = Mathf.Atan2(det, dot) * Mathf.Rad2Deg;
        }
        else
        {
            // Small perturbation for near-zero vectors to avoid a stall
            theta_pos = 1.0f;
        }

        // Step 2: orientation error term
        // Direction vectors in world space
        Vector3 globalEndDir = endEffector.TransformDirection(endEffectorApproachAxis);
        Vector3 globalTargetDir = target.TransformDirection(targetApproachAxis);

        // Convert to the joint local frame
        Vector3 localEndDir = joint.InverseTransformDirection(globalEndDir);
        Vector3 localTargetDir = joint.InverseTransformDirection(globalTargetDir);

        // Project onto the plane orthogonal to the rotation axis
        localEndDir -= Vector3.Project(localEndDir, axis);
        localTargetDir -= Vector3.Project(localTargetDir, axis);

        float theta_ori = 0f;
        if (localEndDir.sqrMagnitude > 0.0001f && localTargetDir.sqrMagnitude > 0.0001f)
        {
            theta_ori = Vector3.SignedAngle(localEndDir, localTargetDir, axis);
        }

        // Step 3: distance-dependent weighting of the two terms
        // Far from the target the position term dominates; within the threshold the orientation
        // weight rises so that the end effector aligns for the grasp.
        float normalizedDist = Mathf.Clamp01(currentDistance / adaptiveThreshold);

        // The position weight is kept at 1.0; reducing it for orientation causes elbow flips.
        float weightPos = 1.0f;

        float baseWeightOri = Mathf.Lerp(0.4f, 0.0f, normalizedDist);
        // Orientation weight only for joints that may affect orientation (wrist)
        float finalWeightOri = baseWeightOri * jointData.orientationInfluence;
        float finalTheta = (theta_pos * weightPos) + (theta_ori * finalWeightOri);
        
        // 4. Rotation damping against oscillation
        joint.Rotate(axis, finalTheta * damping, Space.Self);
    }
}
