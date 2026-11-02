using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Renders the experiment cameras of SceneB at 2048 x 2048 for the paper figure (edit mode, no simulation).
// Batch:  Unity.exe -batchmode -projectPath <UnityRevision> -executeMethod HiResCapture.Batch -quit -logFile <log>
// Editor: menu Tools > Capture high-resolution scene images
public static class HiResCapture
{
    const int Size = 2048;

    [MenuItem("Tools/Capture high-resolution scene images")]
    public static void FromMenu() { Capture(); }

    public static void Batch()
    {
        try { EditorSceneManager.OpenScene("Assets/Scenes/SceneB.unity", OpenSceneMode.Single); Capture(); EditorApplication.Exit(0); }
        catch (System.Exception e) { Debug.LogError("HiResCapture failed: " + e); EditorApplication.Exit(1); }
    }

    static void Capture()
    {
        var socket = Object.FindObjectOfType<SimpleRobotSocket>();
        if (socket == null || socket.cameraMain == null || socket.cameraAux == null) throw new System.InvalidOperationException("SimpleRobotSocket cameras not found");
        string dir = Path.GetFullPath(Path.Combine(Application.dataPath, "../../../../paper/figures"));
        Directory.CreateDirectory(dir);
        Render(socket.cameraMain, Path.Combine(dir, "scene_main_2048.png"));
        Render(socket.cameraAux, Path.Combine(dir, "scene_side_2048.png"));
        Debug.Log("HiResCapture wrote images to " + dir);
    }

    static void Render(Camera cam, string file)
    {
        var rt = new RenderTexture(Size, Size, 24, RenderTextureFormat.ARGB32) { antiAliasing = 8 };
        var previous = cam.targetTexture;
        cam.targetTexture = rt; cam.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(Size, Size, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, Size, Size), 0, 0); tex.Apply();
        cam.targetTexture = previous; RenderTexture.active = null;
        File.WriteAllBytes(file, tex.EncodeToPNG());
        Object.DestroyImmediate(rt); Object.DestroyImmediate(tex);
    }
}
