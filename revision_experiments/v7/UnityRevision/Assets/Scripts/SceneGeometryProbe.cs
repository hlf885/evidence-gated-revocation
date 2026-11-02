using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using PaperRevision;

public class SceneGeometryProbe : MonoBehaviour
{
    [Serializable] public class EntityInfo
    {
        public string name,path;
        public Vector3 position,scale,boundsCenter,boundsSize;
        public int colliders,missingCollisionMeshes;
        public bool rigidbody;
    }
    [Serializable] public class Placement
    {
        public string objectName,containerName,caseName;
        public Vector3 start,end;
        public ScoreSnapshot score;
    }
    [Serializable] public class Report
    {
        public string scope="Original SceneB copied geometry; scripted placement and gravity, no robot or VLM execution",error,unityVersion;
        public List<EntityInfo> entities=new List<EntityInfo>();
        public List<Placement> placements=new List<Placement>();
    }
    private Report report=new Report();
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Boot()
    {
        if(Array.IndexOf(Environment.GetCommandLineArgs(),"-geometryOutput")>=0)
            new GameObject("SceneGeometryProbe").AddComponent<SceneGeometryProbe>();
    }
    IEnumerator Start()
    {
        report.unityVersion=Application.unityVersion; Time.fixedDeltaTime=.02f;
        var args=Environment.GetCommandLineArgs(); string path=args[Array.IndexOf(args,"-geometryOutput")+1];
        IEnumerator suite=Suite();
        while(true)
        {
            bool next=false; object current=null;
            try { next=suite.MoveNext(); if(next)current=suite.Current; }
            catch(Exception ex) { report.error=ex.ToString(); }
            if(!next)break;
            yield return current;
        }
        File.WriteAllText(path,JsonUtility.ToJson(report,true));
        Debug.Log("GEOMETRY_PROBE_COMPLETE placements="+report.placements.Count+" error="+report.error);
        #if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(string.IsNullOrEmpty(report.error)?0:2);
        #endif
    }
    IEnumerator Suite()
    {
        Transform[] all=FindObjectsOfType<Transform>();
        string[] objectNames={"RedCube","GreenBall","YellowCylinder","hammer","Wrench","stapler","Stapler"};
        foreach(Transform t in all.Where(t=>objectNames.Contains(t.name)||t.name.ToLower().Contains("plate")||t.name.ToLower().Contains("bowl")))
        {
            var entity=new Entity{obj=t.gameObject}; Bounds bounds;
            RevisionRuntime.BoundsOf(entity,out bounds);
            string path=t.name; Transform parent=t.parent;
            while(parent!=null){path=parent.name+"/"+path;parent=parent.parent;}
            report.entities.Add(new EntityInfo{name=t.name,path=path,position=t.position,scale=t.lossyScale,
                boundsCenter=bounds.center,boundsSize=bounds.size,colliders=t.GetComponentsInChildren<Collider>().Count(c=>c.enabled&&!c.isTrigger),
                missingCollisionMeshes=t.GetComponentsInChildren<MeshCollider>().Count(c=>c.sharedMesh==null),rigidbody=t.GetComponent<Rigidbody>()!=null});
        }
        var templates=new Dictionary<string,GameObject>();
        foreach(string name in new[]{"RedCube","GreenBall","YellowCylinder","hammer","Wrench"})
        {
            var matches=all.Where(t=>t.name==name).ToArray();
            if(matches.Length!=1)throw new InvalidOperationException("Ambiguous or missing object: "+name);
            templates.Add(name,matches[0].gameObject);
        }
        // Freeze the copied robot; deactivate only the two source objects that will be cloned.
        foreach(Rigidbody body in FindObjectsOfType<Rigidbody>())body.isKinematic=true;
        foreach(GameObject original in templates.Values)original.SetActive(false);
        foreach(string containerName in new[]{"bowl02","plate02"})
        {
            var matches=all.Where(t=>t.name==containerName).ToArray();
            if(matches.Length!=1)throw new InvalidOperationException("Ambiguous or missing container: "+containerName);
            GameObject container=matches[0].gameObject; Bounds containerBounds;
            if(!RevisionRuntime.BoundsOf(new Entity{obj=container},out containerBounds))throw new InvalidOperationException("No container collider");
            foreach(var pair in templates)
            {
                GameObject clone=Instantiate(pair.Value); clone.name="Probe_"+pair.Key; clone.SetActive(true);
                clone.transform.localScale=pair.Value.transform.lossyScale;
                foreach(MonoBehaviour behaviour in clone.GetComponentsInChildren<MonoBehaviour>())behaviour.enabled=false;
                Rigidbody body=clone.GetComponent<Rigidbody>();
                if(body==null)throw new InvalidOperationException("Missing source object Rigidbody");
                body.isKinematic=false;body.useGravity=true;body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;
                Physics.SyncTransforms(); Bounds bounds; RevisionRuntime.BoundsOf(new Entity{obj=clone},out bounds);
                Vector3 target=new Vector3(containerBounds.center.x,containerBounds.max.y+.06f,containerBounds.center.z);
                clone.transform.position+=target-new Vector3(bounds.center.x,bounds.min.y,bounds.center.z);
                Physics.SyncTransforms(); Vector3 start=clone.transform.position;
                GameObject evaluator=new GameObject("ProbeEvaluator");var runtime=evaluator.AddComponent<RevisionRuntime>();
                var config=new Configuration{trialId=pair.Key+"_"+containerName,
                    entities=new[]{new EntitySpec{id="obj",sceneName=clone.name,kind="object"},new EntitySpec{id="container",sceneName=containerName,kind="container"}},
                    goals=new[]{new GoalSpec{id="goal",objectId="obj",containerId="container"}}};
                runtime.Configure(config,s=>s.id=="obj"?clone:container);
                for(int step=0;step<150;++step)yield return new WaitForFixedUpdate();
                report.placements.Add(new Placement{objectName=pair.Key,containerName=containerName,caseName="gravity_center_placement",
                    start=start,end=clone.transform.position,score=runtime.Sample(Time.fixedTime)});
                body.useGravity=false;body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;
                clone.transform.position+=Vector3.up*.3f;Physics.SyncTransforms();
                for(int step=0;step<18;++step)yield return new WaitForFixedUpdate();
                report.placements.Add(new Placement{objectName=pair.Key,containerName=containerName,caseName="hovering_negative",
                    start=start,end=clone.transform.position,score=runtime.Sample(Time.fixedTime)});
                Destroy(evaluator);Destroy(clone);yield return null;
            }
        }
        foreach(string containerName in new[]{"bowl02","plate02"})
        foreach(string arrangement in new[]{"side_by_side","stacked","floating_stack"})
        {
            GameObject container=all.Single(t=>t.name==containerName).gameObject;
            Bounds cb;RevisionRuntime.BoundsOf(new Entity{obj=container},out cb);
            var clones=new List<GameObject>(); var specs=new List<EntitySpec>();var goals=new List<GoalSpec>();
            foreach(string objectName in new[]{"RedCube","YellowCylinder"})
            {
                int index=clones.Count; GameObject clone=Instantiate(templates[objectName]);clone.SetActive(true);clone.name="Shared_"+objectName;
                clone.transform.localScale=templates[objectName].transform.lossyScale;
                Rigidbody body=clone.GetComponent<Rigidbody>();body.isKinematic=false;body.useGravity=true;
                body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;
                Physics.SyncTransforms();Bounds b;RevisionRuntime.BoundsOf(new Entity{obj=clone},out b);
                float x=cb.center.x+(arrangement=="side_by_side"?(index==0?-.025f:.025f):0);
                float y=cb.max.y+.03f;
                if(index==1 && arrangement!="side_by_side")
                {Bounds below;RevisionRuntime.BoundsOf(new Entity{obj=clones[0]},out below);y=below.max.y+.01f;}
                clone.transform.position+=new Vector3(x,y,cb.center.z)-new Vector3(b.center.x,b.min.y,b.center.z);
                Physics.SyncTransforms();clones.Add(clone);
                specs.Add(new EntitySpec{id="obj"+index,sceneName=clone.name,kind="object"});
                goals.Add(new GoalSpec{id="g"+index,objectId="obj"+index,containerId="container"});
                for(int step=0;step<100;++step)yield return new WaitForFixedUpdate();
            }
            specs.Add(new EntitySpec{id="container",sceneName=containerName,kind="container"});
            var eval=new GameObject("SharedEvaluator");var runtime=eval.AddComponent<RevisionRuntime>();
            runtime.Configure(new Configuration{trialId=containerName+"_"+arrangement,entities=specs.ToArray(),goals=goals.ToArray()},
                s=>s.id=="container"?container:clones[int.Parse(s.id.Substring(3))]);
            if(arrangement=="floating_stack")foreach(var clone in clones)
            {var body=clone.GetComponent<Rigidbody>();body.useGravity=false;body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;clone.transform.position+=Vector3.up*.3f;}
            Physics.SyncTransforms();for(int step=0;step<100;++step)yield return new WaitForFixedUpdate();
            report.placements.Add(new Placement{objectName="RedCube+YellowCylinder",containerName=containerName,caseName=arrangement,
                score=runtime.Sample(Time.fixedTime)});
            if(arrangement=="stacked")
            {
                var top=clones[1];var body=top.GetComponent<Rigidbody>();body.useGravity=false;body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;
                top.transform.position+=Vector3.up*.3f;Physics.SyncTransforms();
                for(int step=0;step<50;++step)yield return new WaitForFixedUpdate();
                report.placements.Add(new Placement{objectName="RedCube+YellowCylinder",containerName=containerName,caseName="upper_hovering",
                    score=runtime.Sample(Time.fixedTime)});
            }
            Destroy(eval);foreach(var clone in clones)Destroy(clone);yield return null;
        }
    }
}
