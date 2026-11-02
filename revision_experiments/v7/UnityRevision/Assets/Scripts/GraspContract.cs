using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

// Shared execution contract; simulation identity is explicitly privileged.
public static class GraspContract
{
    public const float LiftFraction=.8f;
    public static float RequiredLift(float commandedHeight){return commandedHeight*LiftFraction;}
    public static bool LiftPasses(float displacement,float commandedHeight)
    {return commandedHeight>0&&!float.IsNaN(displacement)&&!float.IsInfinity(displacement)&&displacement>=RequiredLift(commandedHeight);}
    public static string Normalize(string name)
    {return (name??"").Trim().ToLowerInvariant().Replace(" ","").Replace("_","");}
    public class Selection {public Collider collider;public Rigidbody body;public string reason;}
    public static Selection Select(IEnumerable<Collider> candidates,string requested,Transform expected,Vector3 gripper)
    {
        var choices=candidates.Where(c=>c!=null&&c.enabled&&!c.isTrigger&&c.gameObject.activeInHierarchy&&c.attachedRigidbody!=null)
            .OrderBy(c=>Vector3.Distance(gripper,c.transform.position)).GroupBy(c=>c.attachedRigidbody).Select(g=>g.First()).ToArray();
        if(expected!=null)
        {
            var found=choices.Where(c=>c.attachedRigidbody.transform==expected).ToArray();
            if(found.Length==1)return new Selection{collider=found[0],body=found[0].attachedRigidbody,reason="registered_identity"};
            return new Selection{reason="target_not_found"};
        }
        if(!string.IsNullOrWhiteSpace(requested))
        {
            string key=Normalize(requested);
            var matches=choices.Where(c=>Normalize(c.attachedRigidbody.name)==key).ToArray();
            if(matches.Length!=1)return new Selection{reason=matches.Length==0?"target_not_found":"ambiguous_target"};
            return new Selection{collider=matches[0],body=matches[0].attachedRigidbody,reason="exact_name"};
        }
        if(choices.Length==0)return new Selection{reason="no_candidates"};
        return new Selection{collider=choices[0],body=choices[0].attachedRigidbody,reason="unnamed_nearest"};
    }
}
