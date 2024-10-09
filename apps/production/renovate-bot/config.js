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
        matchUpdateTypes: ["minor", "patch", "pin", "digest"],
        automerge: true
      }
    ],
    forkProcessing: "enabled"
}
