using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using PaperRevision;

// Read-only instrumentation. It never chooses targets, alters physics or accepts actions.
public partial class SimpleRobotSocket
{
    [Serializable] public class DiagnosticBody
    {
        public string id,name;
        public Vector3 position,rigidbodyPosition,rotation,velocity,angularVelocity,scale;
        public float bottom,top;
        public bool hasCollider,hasRigidbody,kinematic,jointPresent;
        public Vector3 objectAnchor,connectedAnchor;
        public float jointGap;
    }
    [Serializable] public class DiagnosticFrame
    {
        public string stage,phase,action,requestedId;
        public int frame;
        public float time,fixedTime,proxyToGripper,lastDeltaY;
        public Vector3 gripper,ikTarget,proxyTransform,proxyRigidbody;
        public DiagnosticBody requested,tracked;
        public HoldingFeedback holding;
    }
    [Serializable] public class DiagnosticScan
    {
        public float time,fixedTime;
        public string requestedName,selectedName,selectionMode;
        public Vector3 gripper;
        public DiagnosticBody[] candidates;
        public DiagnosticBody requested;
    }
    [Serializable] public class DiagnosticTrace
    {
        public string scope="read-only development instrumentation; not an independent grasp oracle";
        public DiagnosticFrame[] frames;
        public DiagnosticScan[] scans;
        public int droppedFrames;
    }
    private bool diagnosticActive;
    private string diagnosticStage="",diagnosticAction="",diagnosticRequestedId="";
    private Transform diagnosticRequested,diagnosticTracked;
    private Coroutine diagnosticLoop;
    private readonly List<DiagnosticFrame> diagnosticFrames=new List<DiagnosticFrame>();
    private readonly List<DiagnosticScan> diagnosticScans=new List<DiagnosticScan>();
    private int diagnosticDropped;
    private bool DiagnosticsEnabled { get {return Environment.GetCommandLineArgs().Contains("-revisionDiagnostics");} }

    DiagnosticBody DiagnosticRead(Transform obj)
    {
        if(obj==null)return null;
        var runtime=GetComponent<RevisionRuntime>();
        Entity entity=runtime==null?null:runtime.registry.FindOwner(obj);
        var rb=obj.GetComponent<Rigidbody>();var col=obj.GetComponent<Collider>();
        var sample=new DiagnosticBody{id=entity==null?"unregistered":entity.spec.id,name=obj.name,
            position=obj.position,rotation=obj.eulerAngles,scale=obj.lossyScale,hasRigidbody=rb!=null,
            hasCollider=col!=null&&col.enabled,rigidbodyPosition=rb==null?obj.position:rb.position,
            velocity=rb==null?Vector3.zero:rb.velocity,angularVelocity=rb==null?Vector3.zero:rb.angularVelocity,
            kinematic=rb!=null&&rb.isKinematic,bottom=col==null?obj.position.y:col.bounds.min.y,
            top=col==null?obj.position.y:col.bounds.max.y};
        var joint=obj.GetComponent<FixedJoint>();
        if(joint!=null&&joint.connectedBody!=null)
        {
            sample.jointPresent=true;
            sample.objectAnchor=joint.transform.TransformPoint(joint.anchor);
            sample.connectedAnchor=joint.connectedBody.transform.TransformPoint(joint.connectedAnchor);
            sample.jointGap=Vector3.Distance(sample.objectAnchor,sample.connectedAnchor);
        }
        return sample;
    }
    void DiagnosticCapture(string phase)
    {
        if(!diagnosticActive)return;
        if(diagnosticFrames.Count>=25000){diagnosticDropped++;return;}
        var runtime=GetComponent<RevisionRuntime>();
        diagnosticFrames.Add(new DiagnosticFrame{stage=diagnosticStage,phase=phase,
            action=diagnosticAction,requestedId=diagnosticRequestedId,frame=Time.frameCount,
            time=Time.time,fixedTime=Time.fixedTime,gripper=gripperCenter.position,
            ikTarget=ikTarget.position,proxyTransform=jointProxyAnchor.transform.position,
            proxyRigidbody=jointProxyRB.position,proxyToGripper=Vector3.Distance(jointProxyRB.position,gripperCenter.position),
            lastDeltaY=lastDeltaY,requested=DiagnosticRead(diagnosticRequested),tracked=DiagnosticRead(diagnosticTracked),
            holding=runtime==null?null:RevisionHolding(runtime)});
    }
    void DiagnosticMark(string stage)
    {if(diagnosticActive){diagnosticStage=stage;DiagnosticCapture("marker");}}
    void DiagnosticSelection(string requestedName,Collider[] candidates,Collider selected,string mode)
    {
        if(!diagnosticActive)return;
        if(selected!=null)diagnosticTracked=selected.transform;
        diagnosticScans.Add(new DiagnosticScan{time=Time.time,fixedTime=Time.fixedTime,
            requestedName=requestedName,selectedName=selected==null?null:selected.name,selectionMode=mode,
            gripper=gripperCenter.position,requested=DiagnosticRead(diagnosticRequested),
            candidates=candidates.Select(c=>DiagnosticRead(c.transform)).ToArray()});
        DiagnosticMark("candidate_"+mode);
    }
    IEnumerator DiagnosticFixedSamples()
    {
        while(diagnosticActive)
        {yield return new WaitForFixedUpdate();DiagnosticCapture("wait_for_fixed_update");}
    }
    void LateUpdate(){DiagnosticCapture("late_update");}
    void BeginDiagnostic(string action,string requestedId,Transform requested)
    {
        if(!DiagnosticsEnabled)return;
        if(diagnosticLoop!=null)StopCoroutine(diagnosticLoop);
        diagnosticFrames.Clear();diagnosticScans.Clear();diagnosticDropped=0;
        diagnosticAction=action;diagnosticRequestedId=requestedId;diagnosticRequested=requested;
        diagnosticTracked=targetCube;diagnosticStage="command_start";diagnosticActive=true;
        DiagnosticCapture("marker");diagnosticLoop=StartCoroutine(DiagnosticFixedSamples());
    }
    DiagnosticTrace EndDiagnostic()
    {
        if(!diagnosticActive)return null;
        DiagnosticMark("command_end");diagnosticActive=false;
        if(diagnosticLoop!=null)StopCoroutine(diagnosticLoop);diagnosticLoop=null;
        return new DiagnosticTrace{frames=diagnosticFrames.ToArray(),scans=diagnosticScans.ToArray(),droppedFrames=diagnosticDropped};
    }
    IEnumerator DiagnosticWindow(RevisionResponse response)
    {
        if(!DiagnosticsEnabled)throw new InvalidOperationException("Diagnostic process required");
        BeginDiagnostic("OBSERVATION_HOLD",diagnosticRequestedId,diagnosticRequested);
        DiagnosticMark("observe_1s");
        yield return new WaitForSeconds(1f);
        response.diagnostics=EndDiagnostic();
    }
}
