FROM ubuntu:24.04

LABEL com.zsocks.provider="pia" \
      com.zsocks.socks5="true" \
      com.zsocks.vpn="piactl"

ARG PIA_INSTALLER_URL="https://installers.privateinternetaccess.com/download/pia-linux-3.7.2-08420.run"
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/piavpn/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/piavpn/lib"

COPY installers/ /tmp/installers/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dbus \
        dbus-user-session \
        gnupg \
        iproute2 \
        iptables \
        kmod \
        libdbus-1-3 \
        libfontconfig1 \
        libfreetype6 \
        libgl1 \
        libglib2.0-0 \
        libnl-3-200 \
        libnl-genl-3-200 \
        libnl-route-3-200 \
        libnsl2 \
        libopengl0 \
        libice6 \
        libsm6 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        lsb-release \
        microsocks \
        procps \
        psmisc \
        python3 \
        sudo \
        tini \
        util-linux \
        wireguard-tools \
    && if [ -f /tmp/installers/pia-linux.run ]; then \
        cp /tmp/installers/pia-linux.run /tmp/pia-linux.run; \
    else \
        curl -fsSL --retry 3 "$PIA_INSTALLER_URL" -o /tmp/pia-linux.run; \
    fi \
    && useradd -m -s /bin/bash pia-installer \
    && printf 'pia-installer ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/pia-installer \
    && chmod 440 /etc/sudoers.d/pia-installer \
    && mkdir -p /tmp/pia-installer \
    && sh /tmp/pia-linux.run --target /tmp/pia-installer --noexec --keep --nox11 --accept --quiet \
    && chown -R pia-installer:pia-installer /tmp/pia-installer \
    && su - pia-installer -c 'cd /tmp/pia-installer && ./install.sh --skip-service --force-architecture' \
    && ln -sf /opt/piavpn/bin/piactl /usr/local/bin/piactl \
    && ln -sf /opt/piavpn/bin/pia-daemon /usr/local/bin/pia-daemon \
    && command -v piactl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/pia-linux.run /tmp/pia-installer /tmp/installers /etc/sudoers.d/pia-installer

COPY app/docker/proxy/proxy-entrypoint.sh /usr/local/bin/proxy-entrypoint.sh
COPY app/docker/proxy/proxy-control-server.py /usr/local/bin/proxy-control-server.py
RUN chmod +x /usr/local/bin/proxy-entrypoint.sh /usr/local/bin/proxy-control-server.py

EXPOSE 1080 9000
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/proxy-entrypoint.sh"]
