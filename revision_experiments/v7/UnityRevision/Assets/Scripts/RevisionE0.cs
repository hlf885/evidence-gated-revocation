using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;
using PaperRevision;

public class RevisionE0 : MonoBehaviour
{
    [Serializable] public class TestRecord { public string name, detail; public bool passed; }
    [Serializable] public class TestReport
    {
        public string scope="E0 development fixtures, not full robot trials", version="revision-v1", unityVersion, error;
        public List<TestRecord> checks=new List<TestRecord>();
        public List<FaultRecord> faultEvents=new List<FaultRecord>();
        public List<ScoreSnapshot> snapshots=new List<ScoreSnapshot>();
    }
    private readonly TestReport report=new TestReport();
    private readonly List<GameObject> owned=new List<GameObject>();
    private const BindingFlags BF=BindingFlags.Instance|BindingFlags.NonPublic;
    private RevisionRuntime runtime;
    private GameObject cube,plate;
    private string output;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Boot()
    {
        if(Array.IndexOf(Environment.GetCommandLineArgs(),"-revisionOutput")>=0)
            new GameObject("RevisionE0").AddComponent<RevisionE0>();
    }
    IEnumerator Start()
    {
        var args=Environment.GetCommandLineArgs(); output=args[Array.IndexOf(args,"-revisionOutput")+1];
        Time.fixedDeltaTime=.02f; Application.targetFrameRate=120; report.unityVersion=Application.unityVersion;
        IEnumerator suite=Suite();
        while(true)
        {
            object current=null; bool next=false;
            try { next=suite.MoveNext(); if(next) current=suite.Current; }
            catch(Exception ex) { report.error=ex.ToString(); }
            if(!next) break;
            yield return current;
        }
        Cleanup(); Directory.CreateDirectory(Path.GetDirectoryName(output));
        File.WriteAllText(output,JsonUtility.ToJson(report,true));
        bool passed=string.IsNullOrEmpty(report.error)&&report.checks.All(x=>x.passed);
        Debug.Log("REVISION_E0_COMPLETE checks="+report.checks.Count+" passed="+passed);
        #if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(passed?0:2);
        #endif
    }
    GameObject New(string name) { GameObject go=new GameObject(name); owned.Add(go); return go; }
    GameObject Box(string name,Vector3 pos,Vector3 size,bool body)
    {
        var go=New(name); go.transform.position=pos; go.AddComponent<BoxCollider>().size=size;
        if(body) { var rb=go.AddComponent<Rigidbody>(); rb.useGravity=false; }
        return go;
    }
    void Cleanup()
    {
        for(int i=owned.Count-1;i>=0;--i) if(owned[i]!=null) DestroyImmediate(owned[i]);
        owned.Clear(); runtime=null;
    }
    EntitySpec Spec(string id,string name,string kind,params string[] aliases)
    { return new EntitySpec {id=id,sceneName=name,kind=kind,aliases=aliases}; }
    Configuration Config(FaultSpec[] faults=null)
    {
        return new Configuration {trialId="fixture",
            entities=new[]{Spec("red_cube","RedCube","object","red cube","RedCube"),Spec("plate","white plate","container","white plate")},
            goals=new[]{new GoalSpec{id="g1",objectId="red_cube",containerId="plate"}}, faults=faults};
    }
    void Setup(FaultSpec[] faults=null)
    {
        Cleanup(); runtime=New("Evaluator").AddComponent<RevisionRuntime>(); runtime.enabled=false;
        cube=Box("RedCube",new Vector3(0,.031f,0),Vector3.one*.04f,true);
        plate=Box("white plate",Vector3.zero,new Vector3(.4f,.02f,.4f),false);
        runtime.Configure(Config(faults),s=>s.id=="red_cube"?cube:plate); Physics.SyncTransforms();
    }
    void Check(string name,bool passed,string detail="")
    { report.checks.Add(new TestRecord{name=name,passed=passed,detail=detail}); }
    void Reject(string name,Action action)
    {
        bool rejected=false; string detail="";
        try { action(); } catch(ArgumentException ex) { rejected=true; detail=ex.Message; }
        catch(InvalidOperationException ex) { rejected=true; detail=ex.Message; }
        Check(name,rejected,detail);
    }
    ScoreSnapshot Stable(float from=0)
    {
        ScoreSnapshot snapshot=null;
        for(int i=0;i<=16;++i) snapshot=runtime.Sample(from+i*.02f);
        report.snapshots.Add(snapshot); return snapshot;
    }
    IEnumerator Suite()
    {
        Setup();
        foreach(string alias in new[]{"red_cube","red cube","REDCUBE"," RED CUBE "})
            Check("resolve_"+alias,runtime.registry.Resolve(alias,"object").obj==cube);
        Check("container_alias",runtime.registry.Resolve("white plate","container").obj==plate);
        Reject("unknown_id_rejected",()=>runtime.registry.Resolve("yellow_cube"));
        Reject("wrong_kind_rejected",()=>runtime.registry.Resolve("plate","object"));
        Reject("ambiguous_alias_rejected",()=>runtime.registry.Register(Spec("other","Other","object","red cube"),New("Other")));
        Check("registry_unchanged_after_collision",runtime.registry.Resolve("red cube").obj==cube);
        Reject("configuration_not_mutable_mid_trial",()=>runtime.Configure(Config(),s=>cube));

        Setup(); Check("stable_window_required",!runtime.Sample(0).taskSuccess);
        Check("valid_stable_goal",Stable().taskSuccess);
        cube.transform.position+=Vector3.right; Physics.SyncTransforms();
        var displaced=runtime.Sample(.34f); report.snapshots.Add(displaced);
        Check("completed_goal_revoked_after_displacement",!displaced.taskSuccess && displaced.progress==0);
        cube.transform.position-=Vector3.right; Physics.SyncTransforms();
        Check("return_requires_new_stable_window",!runtime.Sample(.36f).taskSuccess);
        Check("return_can_requalify",Stable(.36f).taskSuccess);

        foreach(string scenario in new[]{"wrong_container","hovering","moving","rotating","attached","kinematic","outside","occluding_wrong_support"})
        {
            Setup(); var body=cube.GetComponent<Rigidbody>();
            if(scenario=="wrong_container") { plate.transform.position=Vector3.right; Box("wrong_bowl",Vector3.zero,new Vector3(.4f,.02f,.4f),false); }
            if(scenario=="hovering") cube.transform.position=new Vector3(0,.3f,0);
            if(scenario=="moving") body.velocity=Vector3.right*.5f;
            if(scenario=="rotating") body.angularVelocity=Vector3.up;
            if(scenario=="attached") cube.AddComponent<FixedJoint>();
            if(scenario=="kinematic") body.isKinematic=true;
            if(scenario=="outside") cube.transform.position=Vector3.right;
            if(scenario=="occluding_wrong_support")
            { cube.transform.position+=Vector3.up*.01f; Box("wrong_support",new Vector3(0,.015f,0),new Vector3(.2f,.01f,.2f),false); }
            Physics.SyncTransforms(); ScoreSnapshot snap=Stable();
            Check("reject_"+scenario,!snap.taskSuccess,snap.goals[0].reason);
        }
        Setup(); Stable(); Check("observation_gap_resets_stability",!runtime.Sample(1).taskSuccess);
        Reject("backward_clock_rejected",()=>runtime.Sample(.5f));
        Reject("nan_clock_rejected",()=>runtime.Sample(float.NaN));

        // Two goals demonstrate progress is physical state, independent of method bookkeeping.
        Cleanup(); runtime=New("Evaluator").AddComponent<RevisionRuntime>(); runtime.enabled=false;
        cube=Box("RedCube",new Vector3(-.06f,.031f,0),Vector3.one*.04f,true);
        var second=Box("GreenBall",new Vector3(.06f,.031f,0),Vector3.one*.04f,true);
        plate=Box("white plate",Vector3.zero,new Vector3(.4f,.02f,.4f),false);
        var config=Config(); config.entities=config.entities.Concat(new[]{Spec("green_ball","GreenBall","object")}).ToArray();
        config.goals=config.goals.Concat(new[]{new GoalSpec{id="g2",objectId="green_ball",containerId="plate"}}).ToArray();
        runtime.Configure(config,s=>s.id=="red_cube"?cube:s.id=="green_ball"?second:plate); Physics.SyncTransforms();
        Check("two_goals_complete",Stable().progress==1);
        second.transform.position+=Vector3.right; Physics.SyncTransforms();
        var half=runtime.Sample(.34f); report.snapshots.Add(half); Check("progress_decreases_to_half",half.progress==.5f&&!half.taskSuccess);

        // A controlled box stack actually requires indirect support (unlike toppled shapes).
        Cleanup();runtime=New("StackEvaluator").AddComponent<RevisionRuntime>();runtime.enabled=false;
        cube=Box("RedCube",new Vector3(0,.031f,0),Vector3.one*.04f,true);
        second=Box("GreenBall",new Vector3(0,.071f,0),Vector3.one*.04f,true);
        plate=Box("white plate",Vector3.zero,new Vector3(.4f,.02f,.4f),false);
        runtime.Configure(config,s=>s.id=="red_cube"?cube:s.id=="green_ball"?second:plate);Physics.SyncTransforms();
        var stacked=Stable();Check("indirect_support_chain_accepted",stacked.taskSuccess&&stacked.goals[1].supportEntity=="red_cube>plate",stacked.goals[1].supportEntity);
        cube.transform.position+=Vector3.right;Physics.SyncTransforms();
        Check("removing_lower_support_invalidates_upper",!runtime.Sample(.34f).goals[1].satisfied);

        // Actual PhysX fault effects, including infinite-joint release.
        foreach(int seed in new[]{17,29,43})
        foreach(string type in new[]{"pre_grasp_offset","container_shift","scripted_grasp_loss"})
        {
            var random=new System.Random(seed); float offset=.02f+(float)random.NextDouble()*.03f;
            var fault=new FaultSpec{id="event_1",type=type,targetId=type=="container_shift"?"plate":"red_cube",
                anchor="goal2_after_pick",offset=new Vector3(offset,0,0)};
            Setup(new[]{fault});
            if(type=="scripted_grasp_loss")
            {
                cube.transform.position=new Vector3(0,.5f,0);
                var joint=cube.AddComponent<FixedJoint>(); joint.breakForce=float.PositiveInfinity;
                cube.GetComponent<Rigidbody>().useGravity=true;
            }
            Physics.SyncTransforms();
            if(type=="scripted_grasp_loss")cube.GetComponent<Rigidbody>().Sleep();
            yield return runtime.Inject("event_1","goal2_after_pick",cube.transform);
            FaultRecord record=runtime.faultRecords[0]; report.faultEvents.Add(record);
            Check("fault_effect_"+type+"_"+seed,record.attempted&&record.applied&&record.observedEffect,record.error);
            Reject("no_repeat_"+type+"_"+seed,()=>runtime.Inject("event_1","goal2_after_pick",cube.transform).MoveNext());
        }
        Setup(new[]{new FaultSpec{id="unreached",type="pre_grasp_offset",targetId="red_cube",anchor="later",offset=Vector3.right*.03f}});
        Check("unreached_event_retained",runtime.faultRecords.Count==1&&!runtime.faultRecords[0].attempted);
        yield return runtime.Inject("unreached","wrong_anchor",cube.transform);
        report.faultEvents.Add(runtime.faultRecords[0]);
        Check("wrong_anchor_not_applied",runtime.faultRecords[0].attempted&&!runtime.faultRecords[0].applied);
        Setup(new[]{new FaultSpec{id="not_held",type="scripted_grasp_loss",targetId="red_cube",anchor="pick"}});
        yield return runtime.Inject("not_held","pick",null); report.faultEvents.Add(runtime.faultRecords[0]);
        Check("not_held_not_applied",!runtime.faultRecords[0].applied&&runtime.faultRecords[0].error=="target_not_held");
        Reject("unscheduled_event_rejected",()=>runtime.Inject("unknown","pick",null).MoveNext());

        // Exercise the patched original command entry before its IK branch.
        Cleanup(); var controller=New("Controller").AddComponent<SimpleRobotSocket>(); controller.enabled=false;
        cube=Box("RedCube",new Vector3(0,.031f,0),Vector3.one*.04f,true);
        plate=Box("white plate",Vector3.zero,new Vector3(.4f,.02f,.4f),false);
        string response=""; controller.revisionResponseSink=x=>response=x;
        var request=new SimpleRobotSocket.RevisionRequest{requestId="configure-1",configuration=Config()};
        string command="REV_CONFIG:"+JsonUtility.ToJson(request);
        typeof(SimpleRobotSocket).GetField("originalAction",BF).SetValue(controller,command);
        var method=typeof(SimpleRobotSocket).GetMethod("ProcessCommand",BF);
        yield return controller.StartCoroutine((IEnumerator)method.Invoke(controller,new object[]{command.ToUpperInvariant()}));
        var parsed=JsonUtility.FromJson<SimpleRobotSocket.RevisionResponse>(response.Substring("REVISION:".Length));
        Check("original_entry_configuration_roundtrip",parsed.ok&&parsed.requestId=="configure-1",parsed.error);
        command="REV_SCORE:"+JsonUtility.ToJson(new SimpleRobotSocket.RevisionRequest{requestId="score-1",trialId="fixture"});
        typeof(SimpleRobotSocket).GetField("originalAction",BF).SetValue(controller,command);
        yield return controller.StartCoroutine((IEnumerator)method.Invoke(controller,new object[]{command.ToUpperInvariant()}));
        parsed=JsonUtility.FromJson<SimpleRobotSocket.RevisionResponse>(response.Substring("REVISION:".Length));
        Check("original_entry_offline_score_channel",parsed.ok&&parsed.score.channel=="offline_score",parsed.error);
        Check("isolated_command_port",controller.revisionCommandPort==5505&&controller.pythonServerPort==5506);
        command="REV_SCORE:"+JsonUtility.ToJson(new SimpleRobotSocket.RevisionRequest{requestId="wrong-trial",trialId="other"});
        typeof(SimpleRobotSocket).GetField("originalAction",BF).SetValue(controller,command);
        yield return controller.StartCoroutine((IEnumerator)method.Invoke(controller,new object[]{command.ToUpperInvariant()}));
        parsed=JsonUtility.FromJson<SimpleRobotSocket.RevisionResponse>(response.Substring("REVISION:".Length));
        Check("cross_trial_query_rejected",!parsed.ok&&parsed.error=="Trial ID mismatch");
        // Existence of a constraint is insufficient evidence of actual holding.
        var proxy=New("HoldingProxy");proxy.transform.position=cube.transform.position;
        var proxyBody=proxy.AddComponent<Rigidbody>();proxyBody.isKinematic=true;
        cube.GetComponent<Rigidbody>().isKinematic=true;
        var grasp=cube.AddComponent<FixedJoint>();grasp.autoConfigureConnectedAnchor=false;
        grasp.connectedBody=proxyBody;grasp.anchor=Vector3.zero;grasp.connectedAnchor=Vector3.zero;
        controller.targetCube=cube.transform;Physics.SyncTransforms();
        var holdingMethod=typeof(SimpleRobotSocket).GetMethod("RevisionHolding",BF);
        var currentRuntime=controller.GetComponent<RevisionRuntime>();
        var held=(SimpleRobotSocket.HoldingFeedback)holdingMethod.Invoke(controller,new object[]{currentRuntime});
        Check("coincident_joint_reports_holding",held.state=="HOLDING"&&held.objectId=="red_cube");
        proxy.transform.position+=Vector3.right*.1f;Physics.SyncTransforms();
        held=(SimpleRobotSocket.HoldingFeedback)holdingMethod.Invoke(controller,new object[]{currentRuntime});
        Check("separated_joint_reports_unknown",held.state=="UNKNOWN"&&held.reason=="joint_anchor_separation");
        DestroyImmediate(grasp);
        held=(SimpleRobotSocket.HoldingFeedback)holdingMethod.Invoke(controller,new object[]{currentRuntime});
        Check("removed_joint_reports_empty",held.state=="EMPTY");
        command="REV_END:"+JsonUtility.ToJson(new SimpleRobotSocket.RevisionRequest{requestId="end-1",trialId="fixture"});
        typeof(SimpleRobotSocket).GetField("originalAction",BF).SetValue(controller,command);
        yield return controller.StartCoroutine((IEnumerator)method.Invoke(controller,new object[]{command.ToUpperInvariant()}));
        yield return null;
        parsed=JsonUtility.FromJson<SimpleRobotSocket.RevisionResponse>(response.Substring("REVISION:".Length));
        Check("trial_teardown_keeps_score",parsed.ok&&parsed.score!=null&&controller.GetComponent<RevisionRuntime>()==null);
    }
}
