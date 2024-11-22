module.exports = {
  repositories: [
    "josmase/flux",
    //"josmase/downloader",
    //"josmase/ansible",
    //"josmase/bloh",
    //"josmase/boplats-map",
    //"josmase/workflows",
    //"josmase/devcontainer-templates",
  ],
  gitAuthor: "Renovate Bot <bot@renovateapp.com>",
  platform: "github",
  requireConfig: "required",
  onboarding: true,
  packageRules: [
    {
      packagePatterns: [
        "^artifactory.local.hejsan.xyz\\/docker\\/linuxserver\\/",
      ],
      versioning: `regex:^
(?<compatibility>version-|v)?
(?<major>\d+)\.(?<minor>\d+)(\.(?<patch>\d+))?
(?:
  [\.-]?
  (?<build>(\d+-)?(?:ls)?\d+)
)?
$`,
    },
    {
      matchUpdateTypes: ["minor", "patch", "pin", "digest"],
      automerge: true,
    },
  ],
  forkProcessing: "enabled",
  extends: ["config:best-practices"],
};
