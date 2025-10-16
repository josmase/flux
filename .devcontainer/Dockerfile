FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04@sha256:81380e4c9c14e8a629ff39029639e4b7893e67400246fa7782a0fe7dc193a02a

# Define default values for tools, empty values means that they lead to the latest available version being used.
ARG K8S_VERSION=""
ARG K9S_VERSION=""
ARG FLUX_VERSION=""
ARG SOPS_VERSION=""
ARG AGE_VERSION=""
ARG YQ_VERSION=""
ARG KUSTOMIZE_VERSION=""
ARG KUBECONFORM_VERSION=""

ENV DEFAULT_USER=developer
ENV DEFAULT_USER_HOME=/home/${DEFAULT_USER}

# Install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    git \
    bash \
    unzip \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create default user
RUN useradd -m ${DEFAULT_USER}
USER ${DEFAULT_USER}
WORKDIR ${DEFAULT_USER_HOME}

USER root

# Add install_from_github to the image
COPY install_from_github.sh /usr/local/bin/install_from_github.sh
RUN chmod +x /usr/local/bin/install_from_github.sh

# Install Kubernetes CLI
COPY install_kubectl.sh /tmp/install_kubectl.sh
RUN sh /tmp/install_kubectl.sh

# Install k9s
RUN install_from_github.sh derailed/k9s k9s_Linux_amd64.tar.gz k9s $K9S_VERSION

# Install Flux CLI
RUN install_from_github.sh fluxcd/flux2 flux_VERSION_linux_amd64.tar.gz flux $FLUX_VERSION

# Install secret generators and managers
## Install sops
RUN install_from_github.sh getsops/sops sops-vVERSION.linux.amd64 sops $SOPS_VERSION
RUN install_from_github.sh FiloSottile/age  age-vVERSION-linux-amd64.tar.gz age $AGE_VERSION

# Install validation requirements
RUN install_from_github.sh mikefarah/yq  yq_linux_amd64.tar.gz  yq $YQ_VERSION \
    && mv /usr/local/bin/yq_linux_amd64 /usr/local/bin/yq 
RUN install_from_github.sh kubernetes-sigs/kustomize kustomize_vVERSION_linux_amd64.tar.gz kustomize $KUSTOMIZE_VERSION

## Install kubeconform
RUN install_from_github.sh yannh/kubeconform kubeconform-linux-amd64.tar.gz kubeconform $KUBECONFORM_VERSION

# Switch back to default user
USER ${DEFAULT_USER}
WORKDIR ${DEFAULT_USER_HOME}
