using UnityEditor;
using UnityEditor.SceneManagement;

public static class RevisionBatch
{
    public static void Start()
    {
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        EditorApplication.isPlaying = true;
    }
}
