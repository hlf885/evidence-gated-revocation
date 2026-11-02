using System;
using System.Collections.Generic;
using UnityEngine;
using PaperRevision;

public partial class SimpleRobotSocket
{
    private Transform revisionExpectedPick;
    private string revisionGraspFailure="";
    private int completionSequence;
    [Serializable] public class GoalWatch
    {public string goalId,state,reason;public float overlap;}
    [Serializable] public class WatchSnapshot
    {
        public string channel="completion_watchdog",trialId;
        public int sequence;
        public float simulationTime;
        public GoalWatch[] goals;
    }
    WatchSnapshot ObserveCompletion(RevisionRuntime runtime)
    {
        // Revocation evidence only. Never calls the independent scorer, and never
        // creates a completed marker. CONSISTENT is not a fresh success certificate.
        var items=new List<GoalWatch>();
        foreach(var goal in runtime.configuration.goals)
        {
            var item=new GoalWatch{goalId=goal.id,state="UNKNOWN",reason="missing_observation"};items.Add(item);
            try
            {
                var obj=runtime.registry.Resolve(goal.objectId,"object");var container=runtime.registry.Resolve(goal.containerId,"container");
                Bounds a,b;var body=obj.obj.GetComponent<Rigidbody>();
                if(body==null||!RevisionRuntime.BoundsOf(obj,out a)||!RevisionRuntime.BoundsOf(container,out b))continue;
                float area=a.size.x*a.size.z;
                if(!(area>0))continue;
                item.overlap=Mathf.Max(0,Mathf.Min(a.max.x,b.max.x)-Mathf.Max(a.min.x,b.min.x))*
                    Mathf.Max(0,Mathf.Min(a.max.z,b.max.z)-Mathf.Max(a.min.z,b.min.z))/area;
                if(obj.obj.GetComponentsInChildren<Joint>().Length>0)
                {item.state="INVALID";item.reason="attached";}
                else if(item.overlap<.9f || a.max.y<b.min.y-.015f)
                {item.state="INVALID";item.reason="outside_target";}
                else if(body.isKinematic||!(body.velocity.magnitude<=.02f)||!(body.angularVelocity.magnitude<=.1f)||a.min.y>b.max.y+.015f)
                {item.state="UNKNOWN";item.reason="motion_or_support_uncertain";}
                else {item.state="CONSISTENT";item.reason="no_observed_contradiction";}
            }
            catch(ArgumentException){item.reason="unavailable_identity";}
        }
        return new WatchSnapshot{trialId=runtime.configuration.trialId,sequence=++completionSequence,
            simulationTime=Time.fixedTime,goals=items.ToArray()};
    }
}
