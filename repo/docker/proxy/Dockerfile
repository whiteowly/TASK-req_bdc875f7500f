FROM nginx:1.27-alpine

# Bake the TLS-terminating reverse-proxy config. Certificate material itself
# is mounted at runtime from the ``runtime_secrets`` volume, so no key
# material is checked in or baked into the image.
COPY docker/proxy/nginx.conf /etc/nginx/nginx.conf
COPY docker/proxy/start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 443

CMD ["/start.sh"]
