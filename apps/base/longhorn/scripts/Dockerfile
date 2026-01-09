FROM artifactory.local.hejsan.xyz/docker/bitnami/kubectl:1.32

RUN apt-get update -qq && \
    apt-get install -y -qq jq openssh-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY cleanup-longhorn-duplicate-replicas.sh /usr/local/bin/cleanup-longhorn-duplicate-replicas.sh
COPY find-orphaned-replicas.sh /usr/local/bin/find-orphaned-replicas.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/cleanup-longhorn-duplicate-replicas.sh && \
    chmod +x /usr/local/bin/find-orphaned-replicas.sh && \
    chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
