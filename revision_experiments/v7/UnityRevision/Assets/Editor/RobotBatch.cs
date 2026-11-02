using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
public static class RobotBatch
{
    public static void Start()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/SceneB.unity",OpenSceneMode.Single);
        foreach(MonoBehaviour behaviour in Object.FindObjectsOfType<MonoBehaviour>())
            behaviour.enabled=behaviour is SimpleRobotSocket || behaviour is CCD_IK_Solver;
        EditorApplication.isPlaying=true;
    }
}
