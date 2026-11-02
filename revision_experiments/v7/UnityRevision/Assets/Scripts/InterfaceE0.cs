using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;
using PaperRevision;

public class InterfaceE0:MonoBehaviour
{
    [Serializable] public class CheckResult {public string name;public bool passed;public string detail;}
    [Serializable] public class Report
    {public string scope="v5 synthetic interface fixtures, not robot reliability",error,unityVersion;public List<CheckResult> checks=new List<CheckResult>();}
    private Report report=new Report();private List<GameObject> owned=new List<GameObject>();
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Boot(){if(Environment.GetCommandLineArgs().Contains("-interfaceOutput"))new GameObject("InterfaceE0").AddComponent<InterfaceE0>();}
    void Check(string name,bool passed,string detail=""){report.checks.Add(new CheckResult{name=name,passed=passed,detail=detail});}
    GameObject Box(string name,Vector3 position,bool body=true)
    {
        var go=GameObject.CreatePrimitive(PrimitiveType.Cube);owned.Add(go);go.name=name;go.transform.position=position;go.transform.localScale=Vector3.one*.05f;
        if(body){var rb=go.AddComponent<Rigidbody>();rb.useGravity=false;rb.isKinematic=true;}return go;
    }
    IEnumerator Start()
    {
        report.unityVersion=Application.unityVersion;Time.fixedDeltaTime=.02f;Application.targetFrameRate=60;
        var suite=Suite();
        while(true){object current=null;bool more=false;try{more=suite.MoveNext();if(more)current=suite.Current;}catch(Exception e){report.error=e.ToString();}
            if(!more)break;yield return current;}
        foreach(var go in owned)if(go!=null)DestroyImmediate(go);
        var args=Environment.GetCommandLineArgs();string path=args[Array.IndexOf(args,"-interfaceOutput")+1];
        File.WriteAllText(path,JsonUtility.ToJson(report,true));
        bool ok=string.IsNullOrEmpty(report.error)&&report.checks.All(c=>c.passed);
        Debug.Log("INTERFACE_E0_COMPLETE checks="+report.checks.Count+" passed="+ok);
        #if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(ok?0:2);
        #endif
    }
    IEnumerator Suite()
    {
        Check("lift_boundary_rejects_legacy_log_only_pass",!GraspContract.LiftPasses(.03893f,.05f));
        Check("lift_boundary_accepts_required_value",GraspContract.LiftPasses(GraspContract.RequiredLift(.05f),.05f));
        Check("lift_boundary_rejects_nan_infinity",!GraspContract.LiftPasses(float.NaN,.05f)&&!GraspContract.LiftPasses(float.PositiveInfinity,.05f));
        var desired=Box("GreenBall",new Vector3(1,2,0));var wrong=Box("YellowCylinder",new Vector3(0,2,0));
        var a=desired.GetComponent<Collider>();var b=wrong.GetComponent<Collider>();
        var result=GraspContract.Select(new[]{b},"green ball",desired.transform,wrong.transform.position);
        Check("missing_named_target_never_selects_nearest",result.body==null&&result.reason=="target_not_found");
        result=GraspContract.Select(new[]{b,a},"green ball",desired.transform,wrong.transform.position);
        Check("registered_target_wins_over_nearer_wrong_object",result.body==desired.GetComponent<Rigidbody>());
        result=GraspContract.Select(new[]{a},"green",null,desired.transform.position);
        Check("substring_is_not_exact_identity",result.body==null);
        result=GraspContract.Select(new[]{a},"green_ball",null,desired.transform.position);
        Check("normalized_exact_name_resolves",result.body==desired.GetComponent<Rigidbody>());
        var duplicate=Box("Green_Ball",new Vector3(2,2,0));
        result=GraspContract.Select(new[]{a,duplicate.GetComponent<Collider>()},"green ball",null,desired.transform.position);
        Check("ambiguous_name_rejected",result.body==null&&result.reason=="ambiguous_target");
        var child=new GameObject("Shape");owned.Add(child);child.transform.SetParent(desired.transform,false);var childCol=child.AddComponent<BoxCollider>();
        result=GraspContract.Select(new Collider[]{a,childCol},"green ball",desired.transform,desired.transform.position);
        Check("compound_colliders_resolve_one_rigidbody",result.body==desired.GetComponent<Rigidbody>());
        result=GraspContract.Select(new[]{b},"",null,wrong.transform.position);
        Check("explicitly_unnamed_selection_retains_legacy_behavior",result.body==wrong.GetComponent<Rigidbody>());
        foreach(var go in owned.ToArray())if(go!=null)DestroyImmediate(go);owned.Clear();

        var cube=Box("Held",new Vector3(0,2,0));var plate=Box("Plate",new Vector3(5,0,0),false);
        var proxy=Box("Proxy",cube.transform.position);DestroyImmediate(proxy.GetComponent<Collider>());
        var host=new GameObject("Controller");owned.Add(host);var controller=host.AddComponent<SimpleRobotSocket>();controller.enabled=false;
        var runtime=host.AddComponent<RevisionRuntime>();
        runtime.Configure(new Configuration{trialId="holding_fixture",entities=new[]{
            new EntitySpec{id="held",sceneName="Held",kind="object",aliases=new string[0]},
            new EntitySpec{id="plate",sceneName="Plate",kind="container",aliases=new string[0]}},
            goals=new[]{new GoalSpec{id="g1",objectId="held",containerId="plate"}},
            faults=new[]{new FaultSpec{id="drop",type="scripted_grasp_loss",targetId="held",anchor="probe",observeSeconds=1f}}},
            spec=>spec.id=="held"?cube:plate);
        var body=cube.GetComponent<Rigidbody>();body.isKinematic=false;body.useGravity=true;
        var joint=cube.AddComponent<FixedJoint>();joint.autoConfigureConnectedAnchor=false;joint.connectedBody=proxy.GetComponent<Rigidbody>();
        joint.anchor=Vector3.zero;joint.connectedAnchor=Vector3.zero;controller.targetCube=cube.transform;
        var method=typeof(SimpleRobotSocket).GetMethod("RevisionHolding",BindingFlags.Instance|BindingFlags.NonPublic);
        yield return new WaitForSeconds(.5f);
        float maxGap=0;int heldSamples=0;
        for(int i=0;i<50;i++)
        {yield return new WaitForFixedUpdate();var h=(SimpleRobotSocket.HoldingFeedback)method.Invoke(controller,new object[]{runtime});
            maxGap=Mathf.Max(maxGap,h.jointGap);if(h.state=="HOLDING"&&h.objectId=="held")heldSamples++;}
        Check("known_connected_body_stays_held_for_50_steps",heldSamples==50,"max_gap_m="+maxGap.ToString("R"));
        // A constructed inconsistent configuration, not a claim of sensor accuracy.
        proxy.transform.position+=Vector3.right*.1f;Physics.SyncTransforms();
        var stressed=(SimpleRobotSocket.HoldingFeedback)method.Invoke(controller,new object[]{runtime});
        Check("constructed_separation_returns_unknown",stressed.state=="UNKNOWN"&&stressed.jointGap>.03f);
        proxy.transform.position-=Vector3.right*.1f;Physics.SyncTransforms();yield return new WaitForSeconds(.2f);
        Vector3 before=body.position;yield return runtime.Inject("drop","probe",cube.transform);
        var empty=(SimpleRobotSocket.HoldingFeedback)method.Invoke(controller,new object[]{runtime});
        Check("removed_connection_reports_empty",empty.state=="EMPTY");
        Check("unobstructed_released_body_actually_falls",before.y-body.position.y>.1f,"drop_m="+(before.y-body.position.y).ToString("R"));
        var record=runtime.faultRecords.Single();
        Check("shared_injection_records_effect_and_fixed_wait",record.applied&&record.observedEffect&&record.wakeAfterFixedWaitAt>record.attemptedAt);
    }
}
