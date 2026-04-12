FROM registry.access.redhat.com/ubi9/ubi:9.5@sha256:d07a5e080b8a9b3624d3c9cfbfada9a6baacd8e6d4065118f0e80c71ad518044

RUN dnf install -y squid-5.5 && dnf clean all

COPY squid.conf /etc/squid/squid.conf
COPY --chmod=755 entrypoint.sh /usr/local/bin/proxy-entrypoint.sh

EXPOSE 3128

USER 1000

ENTRYPOINT ["/usr/local/bin/proxy-entrypoint.sh"]
CMD ["-NYC"]
