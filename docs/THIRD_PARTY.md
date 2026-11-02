# Third-party assets

The Unity scene `revision_experiments/v7/UnityRevision/Assets/Scenes/SceneB.unity` uses the assets below.
They are not redistributed in this repository; each remains under its own license. Obtain each one from its
source and place it in `revision_experiments/v7/UnityRevision/Assets/` so that the folder names match the tables. Unity resolves the
scene references through the `.meta` GUIDs of the imported packages; keep the original package contents
unchanged.

## Robot, table and target objects

These come from the *Pick-and-Place* tutorial project of the
[Unity Robotics Hub](https://github.com/Unity-Technologies/Unity-Robotics-Hub), folder
`tutorials/pick_and_place/PickAndPlaceProject/Assets/`. The `.meta` GUIDs used by the scene were checked
against commit `b8d1e1d4c76c9ce75fc145cdbf55a9072cc77364`.

| folder under `Assets/` | contents used | license |
|---|---|---|
| `URDF/niryo_one/niryo_one_urdf` | Niryo One arm and gripper: meshes, link and gripper prefabs | GNU GPL v3 (Niryo One URDF; see the `LICENSE` file in that folder) |
| `Prefabs` | `Table.prefab`, `Target.prefab` | Apache License 2.0 (Unity Robotics Hub) |
| `Environment` | `ModTable.fbx`, `SymmetryCube.fbx` | Apache License 2.0 (Unity Robotics Hub) |
| `Materials` | `NavyFloor.mat`, `NonsymmetricCubeTexture.mat/.png` | Apache License 2.0 (Unity Robotics Hub) |

Copy the four folders together with their `.meta` files, so that the GUIDs referenced by the scene resolve.
From the repository root, in Git Bash or a Linux/macOS shell:

```bash
git clone --filter=blob:none --sparse https://github.com/Unity-Technologies/Unity-Robotics-Hub.git /tmp/urh
git -C /tmp/urh sparse-checkout set tutorials/pick_and_place/PickAndPlaceProject/Assets
SRC=/tmp/urh/tutorials/pick_and_place/PickAndPlaceProject/Assets
DST=revision_experiments/v7/UnityRevision/Assets
mkdir -p "$DST/URDF/niryo_one"
cp -r "$SRC/URDF/niryo_one/niryo_one_urdf" "$SRC/URDF/niryo_one/niryo_one_urdf.meta" "$DST/URDF/niryo_one/"
cp "$SRC/URDF/niryo_one.meta" "$DST/URDF/"
for d in Prefabs Environment Materials; do cp -r "$SRC/$d" "$SRC/$d.meta" "$DST/"; done
```

The Hub folders also contain a few files the scene does not use (for example `TargetPlacement.prefab`);
copying them is harmless. The Unity URDF Importer package is not required, because the arm is stored in the
scene as ordinary GameObjects.

## Unity Asset Store packages (decorative and graspable props)

These packages are subject to the Unity Asset Store End User License Agreement. Add each package to your
Asset Store account and import it with the Package Manager (*My Assets*); the import creates the folder listed.

| folder under `Assets/` | Asset Store package | publisher |
|---|---|---|
| `Mugs, Bowls and Plates` | [Plates, Bowls & Mugs Pack](https://assetstore.unity.com/packages/package/146682) | Robot Skeleton |
| `PolyOne/Free Fruits` | [Free Pack - Fruits](https://assetstore.unity.com/packages/package/368828) | PolyOne Studio |
| `NekoLegends/Food` | [Food - Fruits](https://assetstore.unity.com/packages/package/306724) | Neko Legends |
| `JustPlay/Household props` | [Household props](https://assetstore.unity.com/packages/package/164984) | Maximalist |
| `Office Supplies Low Poly` | [Office Supplies Low Poly](https://assetstore.unity.com/packages/package/105519) | Sten Ulfsson |
| `LowPoly - Free Tools Pack` | [LowPoly - Free Tools Pack](https://assetstore.unity.com/packages/package/332896) | Toonify |
| `Veresen/BasicTools` | [Basic Tools - Low Poly / Stylized](https://assetstore.unity.com/packages/package/294356) | Veresen |

## Included project files

All C# scripts, the editor batch scripts, the scene file, `DepthToGrayscale.shader`, the materials
`RedMat`, `GreenMat`, `YellowMat`, `TransparentRed`, the physics materials `GraspMaterial` and `ZeroFriction`,
and the project settings are covered by the repository license.
