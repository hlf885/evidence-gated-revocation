using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SceneGeometryBatch
{
    public static void Start()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/SceneB.unity",OpenSceneMode.Single);
        // Do not start the original network server, camera/VLM loop or robot controller.
        foreach(MonoBehaviour behaviour in Object.FindObjectsOfType<MonoBehaviour>())
            behaviour.enabled=false;
        EditorApplication.isPlaying=true;
    }
}
