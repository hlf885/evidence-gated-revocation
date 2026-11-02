using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using PaperRevision;

// Explicit privileged observation for a mechanism-isolation experiment.
// It exposes geometry, never independent goal-satisfaction scores.
public partial class SimpleRobotSocket
{
    private string revisionMechanismCondition="";
    private LayoutOffset[] revisionConfiguredOffsets=new LayoutOffset[0];
    private int revisionConfiguredSeed;
    private bool revisionRecoveryResetUsed;
    private readonly Dictionary<Rigidbody,BodyObservation> mechanismInitialBodies=new Dictionary<Rigidbody,BodyObservation>();
    private readonly Dictionary<Collider,bool> mechanismInitialColliders=new Dictionary<Collider,bool>();
    private class CollisionPair {public Collider robot,target;public bool ignored;}
    private readonly List<CollisionPair> mechanismCollisionPairs=new List<CollisionPair>();
    void SaveMechanismPhysics()
    {
        Collider[] robots=GetComponentsInChildren<Collider>();
        foreach(var obj in initialPoses.Keys)
        {
            var body=obj.GetComponent<Rigidbody>();
            if(body!=null)mechanismInitialBodies[body]=BodyObservation.Read(body);
            foreach(var collider in obj.GetComponentsInChildren<Collider>())
            {
                mechanismInitialColliders[collider]=collider.enabled;
                foreach(var robot in robots)if(robot!=collider)
                    mechanismCollisionPairs.Add(new CollisionPair{robot=robot,target=collider,ignored=Physics.GetIgnoreCollision(robot,collider)});
            }
        }
    }
    void RestoreMechanismPhysics()
    {
        foreach(var pair in mechanismInitialBodies)
        {
            var body=pair.Key;if(body==null)continue;var state=pair.Value;
            body.mass=state.mass;body.drag=state.drag;body.angularDrag=state.angularDrag;body.centerOfMass=state.centerOfMass;
            body.inertiaTensor=state.inertiaTensor;body.inertiaTensorRotation=state.inertiaTensorRotation;
            body.useGravity=state.gravity;body.constraints=(RigidbodyConstraints)state.constraints;body.isKinematic=state.kinematic;
            body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;body.WakeUp();
        }
        foreach(var pair in mechanismInitialColliders)if(pair.Key!=null)pair.Key.enabled=pair.Value;
        foreach(var pair in mechanismCollisionPairs)if(pair.robot!=null&&pair.target!=null)
            Physics.IgnoreCollision(pair.robot,pair.target,pair.ignored);
        _savedColliderStates.Clear();hasSavedPhysicsProps=false;targetCube=null;
        if(ikSolver!=null)ikSolver.skipWristRotation=false;
    }
    void AcknowledgeMechanismLoss()
    {
        // Common to all conditions: clean stale grasp bookkeeping without moving objects.
        if(targetCube!=null)
        {
            var body=targetCube.GetComponent<Rigidbody>();
            if(body!=null&&hasSavedPhysicsProps)
            {body.centerOfMass=savedOriginalCenterOfMass;body.angularDrag=savedOriginalAngularDrag;body.WakeUp();}
            foreach(var pair in mechanismCollisionPairs)
                if(pair.robot!=null&&pair.target!=null&&pair.target.transform.IsChildOf(targetCube))
                    Physics.IgnoreCollision(pair.robot,pair.target,pair.ignored);
        }
        foreach(var pair in _savedColliderStates)if(pair.Key!=null)pair.Key.enabled=pair.Value;
        _savedColliderStates.Clear();hasSavedPhysicsProps=false;targetCube=null;
        if(ikSolver!=null)ikSolver.skipWristRotation=false;
    }
    [Serializable] public class ControlledLocation
    {
        public string channel="controlled_simulator_observation",target,action,source;
        public Vector3 position,boundsCenter,boundsSize;
        public float simulationTime;
    }
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void MechanismClock()
    {
        if(Environment.GetCommandLineArgs().Contains("-revisionMechanism"))
        {Application.targetFrameRate=60;QualitySettings.vSyncCount=0;Time.fixedDeltaTime=.02f;}
    }
    void ConfigureMechanism(RevisionRequest request)
    {
        string condition=request.recoveryCondition??"";
        if(condition!=""&&condition!="preserve_resume"&&condition!="preserve_restart"&&condition!="reset_restart")
            throw new ArgumentException("Unknown mechanism condition");
        revisionMechanismCondition=condition;revisionRecoveryResetUsed=false;
        revisionConfiguredOffsets=request.offsets??new LayoutOffset[0];revisionConfiguredSeed=request.seed;
    }
    PoseRecord[] RevisionPoses(RevisionRuntime runtime)
    {
        var poses=new List<PoseRecord>();
        foreach(var spec in runtime.configuration.entities)
        {
            Transform t=runtime.registry.Resolve(spec.id).obj.transform;
            poses.Add(new PoseRecord{id=spec.id,position=t.position,rotation=t.eulerAngles,
                hasRigidbody=t.GetComponent<Rigidbody>()!=null,body=BodyObservation.Read(t.GetComponent<Rigidbody>())});
        }
        if(gripperCenter!=null)poses.Add(new PoseRecord{id="robot_gripper",position=gripperCenter.position,rotation=gripperCenter.eulerAngles});
        return poses.ToArray();
    }
    ControlledLocation ControlledLocate(RevisionRuntime runtime,RevisionRequest request)
    {
        if(revisionMechanismCondition=="")throw new InvalidOperationException("Controlled mechanism configuration required");
        if(request.action!="PICK"&&request.action!="PLACE")throw new ArgumentException("Unsupported localization action");
        Entity entity=runtime.registry.Resolve(request.target,request.action=="PICK"?"object":"container");
        Bounds bounds;
        if(!RevisionRuntime.BoundsOf(entity,out bounds))throw new InvalidOperationException("Target has no collision geometry");
        var location=new ControlledLocation{target=entity.spec.id,action=request.action,boundsCenter=bounds.center,
            boundsSize=bounds.size,simulationTime=Time.fixedTime};
        if(request.action=="PICK")
        {
            location.position=new Vector3(bounds.center.x,bounds.max.y,bounds.center.z);
            location.source="target_collider_bounds_top_center";
        }
        else
        {
            Vector3 origin=new Vector3(bounds.center.x,bounds.max.y+1f,bounds.center.z);
            float nearest=float.PositiveInfinity;Vector3 surface=Vector3.zero;
            foreach(Collider collider in entity.obj.GetComponentsInChildren<Collider>())
            {
                RaycastHit hit;
                if(collider.enabled&&!collider.isTrigger&&collider.gameObject.activeInHierarchy&&
                    collider.Raycast(new Ray(origin,Vector3.down),out hit,bounds.size.y+2f)&&hit.distance<nearest)
                {nearest=hit.distance;surface=hit.point;}
            }
            if(float.IsPositiveInfinity(nearest))throw new InvalidOperationException("No container surface at its canonical center");
            location.position=surface;location.source="named_container_center_surface";
        }
        return location;
    }
    IEnumerator MechanismRecoveryReset(RevisionRuntime runtime,RevisionResponse response)
    {
        // Keep this runtime and its one-shot fault ledger: reset does not rearm faults.
        yield return StartCoroutine(RevisionReset(response));
        foreach(var entry in revisionConfiguredOffsets)
            runtime.registry.Resolve(entry.id,"object").obj.transform.position+=entry.offset;
        UnityEngine.Random.InitState(revisionConfiguredSeed);Physics.SyncTransforms();
        yield return new WaitForSeconds(.5f);
        response.initialState=RevisionPoses(runtime);
    }
}
