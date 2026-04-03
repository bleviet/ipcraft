# Dockerfile for ipcraft toolchain validation box
# This image contains the OS dependencies required to run vendor tools in batch mode.
# Vendor tools (Vivado/Quartus) must be mounted as volumes at runtime.
# Example: docker run -v /opt/Xilinx:/opt/Xilinx -v /intelFPGA:/intelFPGA ...

FROM ubuntu:22.04

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    make \
    libtinfo5 \
    libncurses5 \
    locales \
    && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install uv (used by ipcraft)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /workspace
CMD ["/bin/bash"]
