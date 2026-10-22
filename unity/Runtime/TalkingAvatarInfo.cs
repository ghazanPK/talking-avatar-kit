using UnityEngine;

namespace TalkingAvatarKit
{
    /// <summary>Name, licence and credit of an imported avatar (filled in by the importer from the sidecar).</summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Talking Avatar Kit/Avatar Info")]
    public sealed class TalkingAvatarInfo : MonoBehaviour
    {
        public string slug;
        public string displayName;
        public string licenseId;
        public string licenseUrl;
        [TextArea] public string attribution;
    }
}
