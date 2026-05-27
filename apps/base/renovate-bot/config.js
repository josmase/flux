module.exports = {
  platform: "gitlab",
  endpoint: "https://gitlab.local.hejsan.xyz/api/v4",
  autodiscover: true,
  autodiscoverFilter: "josmase/*",
  gitAuthor: "Renovate Bot <bot@renovateapp.com>",
  requireConfig: "required",
  onboarding: true,
  rebaseWhen: "behind-base-branch",
  labels: ["dependencies", "bot"],
  packageRules: [
    {
      matchPackageNames: [
        "^artifactory\\.local\\.hejsan\\.xyz\\/docker\\/linuxserver\\/",
      ],
      versioning:
        "regex:^(?<compatibility>version-|v)?(?<major>\\d+)\\.(?<minor>\\d+)(\\.(?<patch>\\d+))?(?:[\\.-]?(?<build>(\\d+-)?(?:ls)?\\d+))?$",
      automerge: false,
    },
    { matchUpdateTypes: ["minor", "patch", "pin", "digest"], automerge: true },
  ],
  extends: ["config:best-practices"],
};
