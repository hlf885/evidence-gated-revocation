Shader "Custom/DepthToGrayscale" {
    SubShader {
        // Applies to all render types, including transparent objects and background
        Tags { "RenderType"="Opaque" "RenderType"="TransparentCutout" "RenderType"="Background" }
        Pass {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct appdata {
                float4 vertex : POSITION;
            };

            struct v2f {
                float4 vertex : SV_POSITION;
                float depthInMeters : TEXCOORD0;
            };

            v2f vert (appdata v) {
                v2f o;
                o.vertex = UnityObjectToClipPos(v.vertex);
                // Distance along the camera Z axis in metres
                o.depthInMeters = -(mul(UNITY_MATRIX_MV, v.vertex).z);
                return o;
            }

            fixed4 frag (v2f i) : SV_Target {
                // Depth is scaled to a 2.0 m range so that changes on the table are visible;
                // farther points are written as white (1.0).
                float maxDist = 2.0;
                float normalizedDepth = clamp(i.depthInMeters / maxDist, 0.0, 1.0);
                
                return fixed4(normalizedDepth, normalizedDepth, normalizedDepth, 1.0);
            }
            ENDCG
        }
    }
}
