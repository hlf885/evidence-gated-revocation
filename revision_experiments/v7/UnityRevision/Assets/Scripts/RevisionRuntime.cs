using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace PaperRevision
{
    [Serializable] public class EntitySpec
    {
        public string id, sceneName, kind;
        public string[] aliases;
    }
    [Serializable] public class GoalSpec { public string id, objectId, containerId; }
    [Serializable] public class EvaluationSettings
    {
        // Development fixture values. Calibration on original scenes is still required.
        public float minOverlap = .8f, maxLinearSpeed = .02f, maxAngularSpeed = .1f;
        public float supportDistance = .015f, supportSkin = .004f, stableSeconds = .3f;
        public float maxSampleGap = .041f;
        public bool allowStackedSupport = true;
        public int maxSupportDepth = 4;
    }
    [Serializable] public class FaultSpec
    {
        public string id, type, targetId, anchor;
        public Vector3 offset;
        public float observeSeconds = .6f, minDisplacement = .005f;
    }
    [Serializable] public class Configuration
    {
        public string trialId;
        public EntitySpec[] entities;
        public GoalSpec[] goals;
        public FaultSpec[] faults;
        public EvaluationSettings evaluation = new EvaluationSettings();
    }
    public class Entity
    {
        public EntitySpec spec;
        public GameObject obj;
        public bool Contains(Transform transform)
        { return transform == obj.transform || transform.IsChildOf(obj.transform); }
    }
    public class Registry
    {
        private readonly Dictionary<string, Entity> entries = new Dictionary<string, Entity>();
        private readonly Dictionary<string, string> aliases = new Dictionary<string, string>();
        private static string Key(string value) { return (value ?? "").Trim().ToLowerInvariant(); }
        public void Register(EntitySpec spec, GameObject obj)
        {
            if (obj == null || string.IsNullOrWhiteSpace(spec.id) ||
                (spec.kind != "object" && spec.kind != "container"))
                throw new ArgumentException("Invalid entity definition");
            if (entries.ContainsKey(spec.id) || entries.Values.Any(e => e.obj == obj))
                throw new ArgumentException("Duplicate entity identity: " + spec.id);
            string[] keys = new[] {spec.id}.Concat(spec.aliases ?? new string[0]).Select(Key).Distinct().ToArray();
            if (keys.Any(k => k.Length == 0 || aliases.ContainsKey(k)))
                throw new ArgumentException("Empty or ambiguous alias: " + spec.id);
            entries.Add(spec.id, new Entity {spec = spec, obj = obj});
            foreach (string key in keys) aliases.Add(key, spec.id);
        }
        public Entity Resolve(string name, string kind = null)
        {
            string id;
            if (!aliases.TryGetValue(Key(name), out id)) throw new ArgumentException("Unregistered target: " + name);
            Entity entity = entries[id];
            if (entity.obj == null || !entity.obj.activeInHierarchy) throw new ArgumentException("Inactive target: " + id);
            if (kind != null && entity.spec.kind != kind) throw new ArgumentException("Wrong target kind: " + id);
            return entity;
        }
        public Entity FindOwner(Transform transform)
        { return entries.Values.FirstOrDefault(e=>e.obj!=null && e.Contains(transform)); }
    }
    [Serializable] public class GoalScore
    {
        public string goalId, objectId, containerId, supportEntity, reason;
        public bool instantaneous, satisfied, attached;
        public float overlap, linearSpeed, angularSpeed, stableFor;
    }
    [Serializable] public class ScoreSnapshot
    {
        public string trialId, channel = "offline_score";
        public float simulationTime, progress;
        public bool taskSuccess;
        public GoalScore[] goals;
    }
    [Serializable] public class FaultRecord
    {
        public string id, type, targetId, anchor, error;
        public bool scheduled = true, attempted, applied, observedEffect;
        public Vector3 requestedOffset, before, after;
        public float attemptedAt, observedAt, displacement, wakeAfterFixedWaitAt;
        public bool jointBefore, jointAfter;
        public BodyObservation bodyBefore, bodyAfterJointRemoval, bodyAfter;
    }
    [Serializable] public class BodyObservation
    {
        public bool sleeping,kinematic,gravity;
        public int constraints;
        public float mass,drag,angularDrag;
        public Vector3 position,velocity,angularVelocity,centerOfMass,inertiaTensor;
        public Quaternion inertiaTensorRotation;
        public static BodyObservation Read(Rigidbody body)
        {
            if(body==null)return null;
            return new BodyObservation{sleeping=body.IsSleeping(),kinematic=body.isKinematic,gravity=body.useGravity,
                constraints=(int)body.constraints,mass=body.mass,drag=body.drag,angularDrag=body.angularDrag,
                position=body.position,velocity=body.velocity,angularVelocity=body.angularVelocity,centerOfMass=body.centerOfMass,
                inertiaTensor=body.inertiaTensor,inertiaTensorRotation=body.inertiaTensorRotation};
        }
    }

    // This module owns offline task scoring. Its scores are not controller feedback.
    // No method-specific blackboard, action count or VLM result participates in scoring.
    public class RevisionRuntime : MonoBehaviour
    {
        public Registry registry { get; private set; } = new Registry();
        public Configuration configuration { get; private set; }
        public ScoreSnapshot latest { get; private set; }
        public readonly List<FaultRecord> faultRecords = new List<FaultRecord>();
        private readonly Dictionary<string, float> since = new Dictionary<string, float>();
        private float lastSample = float.NegativeInfinity;
        private readonly Dictionary<string, FaultSpec> faults = new Dictionary<string, FaultSpec>();

        public void Configure(Configuration config, Func<EntitySpec, GameObject> lookup)
        {
            if (configuration != null) throw new InvalidOperationException("One runtime per trial; recreate between trials");
            if (config == null || string.IsNullOrWhiteSpace(config.trialId) || config.entities == null ||
                config.goals == null || config.goals.Length == 0) throw new ArgumentException("Incomplete configuration");
            EvaluationSettings p = config.evaluation;
            if (p == null || !(p.minOverlap > 0 && p.minOverlap <= 1) || !(p.stableSeconds > 0) ||
                !(p.maxLinearSpeed >= 0) || !(p.maxAngularSpeed >= 0) || !(p.supportDistance > 0) ||
                !(p.supportSkin > 0) || !(p.maxSampleGap > 0) || p.maxSupportDepth < 0 || p.maxSupportDepth > 16) throw new ArgumentException("Invalid evaluation settings");
            Registry candidate = new Registry();
            foreach (EntitySpec entity in config.entities) candidate.Register(entity, lookup(entity));
            HashSet<string> goalIds = new HashSet<string>();
            HashSet<string> objectIds = new HashSet<string>();
            foreach (GoalSpec goal in config.goals)
            {
                if (string.IsNullOrWhiteSpace(goal.id) || !goalIds.Add(goal.id)) throw new ArgumentException("Duplicate/empty goal");
                Entity obj = candidate.Resolve(goal.objectId, "object");
                candidate.Resolve(goal.containerId, "container");
                if (!objectIds.Add(obj.spec.id)) throw new ArgumentException("This sequential protocol requires one final goal per object");
            }
            var scheduled = new Dictionary<string, FaultSpec>();
            foreach (FaultSpec fault in config.faults ?? new FaultSpec[0])
            {
                if (string.IsNullOrWhiteSpace(fault.id) || string.IsNullOrWhiteSpace(fault.anchor) || scheduled.ContainsKey(fault.id))
                    throw new ArgumentException("Invalid event identity/anchor");
                if (fault.type != "pre_grasp_offset" && fault.type != "object_shift" && fault.type != "container_shift" && fault.type != "scripted_grasp_loss")
                    throw new ArgumentException("Unknown fault type");
                candidate.Resolve(fault.targetId, fault.type == "container_shift" ? "container" : "object");
                if (!(fault.observeSeconds > 0) || !(fault.minDisplacement > 0) ||
                    float.IsNaN(fault.offset.sqrMagnitude) || float.IsInfinity(fault.offset.sqrMagnitude))
                    throw new ArgumentException("Invalid fault parameters");
                scheduled.Add(fault.id, fault);
            }
            registry = candidate;
            configuration = config;
            foreach (var pair in scheduled)
            {
                faults.Add(pair.Key, pair.Value);
                FaultSpec f = pair.Value;
                faultRecords.Add(new FaultRecord {id=f.id, type=f.type, targetId=f.targetId, anchor=f.anchor, requestedOffset=f.offset});
            }
        }
        void FixedUpdate() { if (configuration != null) Sample(Time.fixedTime); }
        public static bool BoundsOf(Entity entity, out Bounds bounds)
        {
            Collider[] colliders = entity.obj.GetComponentsInChildren<Collider>().Where(c => c.enabled && !c.isTrigger && c.gameObject.activeInHierarchy).ToArray();
            bounds = new Bounds();
            if (colliders.Length == 0) return false;
            bounds = colliders[0].bounds;
            for (int i = 1; i < colliders.Length; ++i) bounds.Encapsulate(colliders[i].bounds);
            return true;
        }
        GoalScore Check(GoalSpec goal)
        {
            GoalScore score = new GoalScore {goalId=goal.id, objectId=goal.objectId, containerId=goal.containerId, reason="not_evaluated"};
            Entity obj, container;
            try { obj=registry.Resolve(goal.objectId,"object"); container=registry.Resolve(goal.containerId,"container"); }
            catch (ArgumentException ex) { score.reason=ex.Message; return score; }
            Rigidbody body=obj.obj.GetComponent<Rigidbody>();
            Bounds a,b;
            if (body == null || !BoundsOf(obj,out a) || !BoundsOf(container,out b)) { score.reason="missing_physics"; return score; }
            EvaluationSettings p=configuration.evaluation;
            score.attached=obj.obj.GetComponentsInChildren<Joint>().Length>0;
            score.linearSpeed=body.velocity.magnitude; score.angularSpeed=body.angularVelocity.magnitude;
            float area=a.size.x*a.size.z;
            score.overlap=area>0 ? Mathf.Max(0,Mathf.Min(a.max.x,b.max.x)-Mathf.Max(a.min.x,b.min.x))*
                Mathf.Max(0,Mathf.Min(a.max.z,b.max.z)-Mathf.Max(a.min.z,b.min.z))/area : 0;
            if (score.attached) { score.reason="still_attached"; return score; }
            if (body.isKinematic) { score.reason="kinematic_object"; return score; }
            if (!(score.linearSpeed<=p.maxLinearSpeed) || !(score.angularSpeed<=p.maxAngularSpeed)) { score.reason="moving"; return score; }
            if (!(score.overlap>=p.minOverlap)) { score.reason="outside_target_footprint"; return score; }
            string support;
            if(!Supported(obj,container,new HashSet<string>(),0,out support)) { score.reason="no_valid_support_chain"; return score; }
            score.supportEntity=support;
            score.instantaneous=true; score.reason="awaiting_stability"; return score;
        }
        bool Supported(Entity obj,Entity container,HashSet<string> visited,int depth,out string support)
        {
            support="";
            if(depth>configuration.evaluation.maxSupportDepth || !visited.Add(obj.spec.id))return false;
            Bounds a,b; if(!BoundsOf(obj,out a)||!BoundsOf(container,out b))return false;
            var p=configuration.evaluation; Rigidbody body=obj.obj.GetComponent<Rigidbody>();
            if(body==null||body.isKinematic||obj.obj.GetComponentsInChildren<Joint>().Length>0||
                !(body.velocity.magnitude<=p.maxLinearSpeed)||!(body.angularVelocity.magnitude<=p.maxAngularSpeed))return false;
            float area=a.size.x*a.size.z;
            float intersection=Mathf.Max(0,Mathf.Min(a.max.x,b.max.x)-Mathf.Max(a.min.x,b.min.x))*
                Mathf.Max(0,Mathf.Min(a.max.z,b.max.z)-Mathf.Max(a.min.z,b.min.z));
            if(area<=0||intersection/area<p.minOverlap)return false;
            // A small footprint grid avoids relying on the center of a hollow/irregular tool.
            foreach(float x in new[]{-.35f,0f,.35f})foreach(float z in new[]{-.35f,0f,.35f})
            {
                // Sample the collider's actual underside, not the AABB minimum.
                // A tilted or hollow tool need not occupy every XZ point of its AABB.
                Vector3 belowPoint=new Vector3(a.center.x+x*a.size.x,a.min.y-.02f,a.center.z+z*a.size.z);
                float bottom=float.PositiveInfinity;
                foreach(Collider own in obj.obj.GetComponentsInChildren<Collider>())
                {
                    RaycastHit surface;
                    if(own.enabled&&!own.isTrigger&&own.gameObject.activeInHierarchy&&
                        own.Raycast(new Ray(belowPoint,Vector3.up),out surface,a.size.y+.04f))
                        bottom=Mathf.Min(bottom,surface.point.y);
                }
                if(float.IsPositiveInfinity(bottom))continue;
                Vector3 origin=new Vector3(belowPoint.x,bottom+p.supportSkin,belowPoint.z);
                var hits=Physics.RaycastAll(origin,Vector3.down,p.supportDistance+p.supportSkin,~0,QueryTriggerInteraction.Ignore);
                Array.Sort(hits,(u,v)=>u.distance.CompareTo(v.distance));
                foreach(var hit in hits)
                {
                    if(obj.Contains(hit.collider.transform))continue;
                    if(hit.normal.y>=.5f)
                    {
                        if(container.Contains(hit.collider.transform)){support=container.spec.id;return true;}
                        Entity below=registry.FindOwner(hit.collider.transform);
                        string chain;
                        if(p.allowStackedSupport&&below!=null&&below.spec.kind=="object"&&
                            Supported(below,container,new HashSet<string>(visited),depth+1,out chain))
                        {support=below.spec.id+">"+chain;return true;}
                    }
                    break; // A wrong nearer support cannot be skipped in favour of the target below it.
                }
            }
            return false;
        }
        public ScoreSnapshot Sample(float now)
        {
            if (configuration == null) throw new InvalidOperationException("Configure first");
            if (float.IsNaN(now) || float.IsInfinity(now) || now<lastSample) throw new ArgumentException("Nonmonotonic sample time");
            if (now-lastSample>configuration.evaluation.maxSampleGap) since.Clear();
            GoalScore[] scores=new GoalScore[configuration.goals.Length];
            for (int i=0;i<scores.Length;++i)
            {
                GoalScore score=Check(configuration.goals[i]);
                if (!score.instantaneous) since.Remove(score.goalId);
                else
                {
                    if (!since.ContainsKey(score.goalId)) since[score.goalId]=now;
                    score.stableFor=now-since[score.goalId];
                    score.satisfied=score.stableFor+0.00001f>=configuration.evaluation.stableSeconds;
                    if (score.satisfied) score.reason="satisfied";
                }
                scores[i]=score;
            }
            lastSample=now;
            latest=new ScoreSnapshot {trialId=configuration.trialId,simulationTime=now,goals=scores,
                progress=(float)scores.Count(s=>s.satisfied)/scores.Length, taskSuccess=scores.All(s=>s.satisfied)};
            return latest;
        }
        public IEnumerator Inject(string eventId, string anchor, Transform heldObject)
        {
            if (!faults.ContainsKey(eventId)) throw new ArgumentException("Unscheduled event: "+eventId);
            FaultSpec spec=faults[eventId]; FaultRecord record=faultRecords.Single(r=>r.id==eventId);
            if (record.attempted) throw new InvalidOperationException("Event already attempted: "+eventId);
            record.attempted=true; record.attemptedAt=Time.fixedTime;
            if (anchor!=spec.anchor) { record.error="anchor_mismatch"; yield break; }
            Entity entity=null;
            try { entity=registry.Resolve(spec.targetId); }
            catch (ArgumentException ex) { record.error=ex.Message; }
            if (entity==null) yield break;
            record.before=entity.obj.transform.position;
            Rigidbody body=entity.obj.GetComponent<Rigidbody>();
            record.bodyBefore=BodyObservation.Read(body);
            Joint[] joints=entity.obj.GetComponentsInChildren<Joint>(); record.jointBefore=joints.Length>0;
            if (spec.type=="scripted_grasp_loss")
            {
                if (heldObject==null || !entity.Contains(heldObject) || body==null || joints.Length==0)
                { record.error="target_not_held"; yield break; }
                // Deliberate constraint removal; this is not a natural force-induced fracture.
                foreach (Joint joint in joints) Destroy(joint);
                // Destroy is deferred. Wake the free body only after the constraint is gone.
                yield return null;
                if(entity.obj.GetComponentsInChildren<Joint>().Length!=0)
                {record.error="joint_removal_not_completed";yield break;}
                record.bodyAfterJointRemoval=BodyObservation.Read(body);
                body.isKinematic=false; body.useGravity=true;
                // Component destruction and the next physics step are distinct boundaries.
                // Wake after a fixed-step wait; no impulse, teleport or repeated fault.
                yield return new WaitForFixedUpdate();
                body.WakeUp();record.wakeAfterFixedWaitAt=Time.fixedTime;record.applied=true;
            }
            else
            {
                if (spec.offset.magnitude<spec.minDisplacement) { record.error="offset_below_observation_threshold"; yield break; }
                entity.obj.transform.position+=spec.offset;
                if (body!=null) body.WakeUp();
                Physics.SyncTransforms(); record.applied=true;
            }
            float end=Time.fixedTime+spec.observeSeconds;
            do { yield return new WaitForFixedUpdate(); } while(Time.fixedTime<end);
            if (entity.obj==null) { record.error="target_destroyed_during_observation"; yield break; }
            record.after=entity.obj.transform.position; record.observedAt=Time.fixedTime;
            record.bodyAfter=BodyObservation.Read(body);
            record.displacement=(record.after-record.before).magnitude;
            record.jointAfter=entity.obj.GetComponentsInChildren<Joint>().Length>0;
            record.observedEffect=spec.type=="scripted_grasp_loss" ?
                !record.jointAfter && record.before.y-record.after.y>=spec.minDisplacement :
                Vector3.Dot(record.after-record.before,spec.offset.normalized)>=spec.minDisplacement;
            if (!record.observedEffect) record.error="effect_not_observed";
        }
    }
}
