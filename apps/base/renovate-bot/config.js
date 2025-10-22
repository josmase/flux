module.exports = {
  repositories: [
    "josmase/flux",
    "josmase/downloader",
    "josmase/ansible",
    "josmase/blog",
    "josmase/boplats-map",
    "josmase/workflows",
    "josmase/devcontainer-templates",
  ],
  gitAuthor: "Renovate Bot <bot@renovateapp.com>",
  platform: "github",
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
  forkProcessing: "enabled",
  extends: ["config:best-practices"],
};
