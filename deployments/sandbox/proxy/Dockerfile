FROM registry.access.redhat.com/ubi9/ubi:9.5

# hadolint ignore=DL3041
RUN dnf install -y squid && dnf clean all

COPY squid.conf /etc/squid/squid.conf
COPY --chmod=755 entrypoint.sh /usr/local/bin/proxy-entrypoint.sh

EXPOSE 3128

USER 1000

ENTRYPOINT ["/usr/local/bin/proxy-entrypoint.sh"]
CMD ["-NYC"]
