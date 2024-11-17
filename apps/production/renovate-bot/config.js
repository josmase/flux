module.exports = {
    autodiscover: true,
    gitAuthor: "Renovate Bot <bot@renovateapp.com>",
    platform: "github",
    requireConfig: "required",
    onboarding: true,
    hostRules: [
        {
            matchHost: "https://artifactory.local.hejsan.xyz/docker",
        }
    ],
    packageRules: [
      {
        "packagePatterns": ["\\/linuxserver\\/"],
        "versioning": "regex:^(?<compatibility>.*?)-(?<major>v?\\d+)\\.(?<minor>\\d+)\\.(?<patch>\\d+)[\\.-]*r?(?<build>\\d+)*-*r?(?<release>\\w+)*"
      },
      {
        matchUpdateTypes: ["minor", "patch", "pin", "digest"],
        automerge: true
      }
    ],
    forkProcessing: "enabled"
}
