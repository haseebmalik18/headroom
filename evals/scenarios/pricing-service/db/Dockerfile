FROM postgres:16-alpine

# tc/netem lets the container model the network hop to a database that runs on
# its own host, instead of Docker's near-zero-latency in-VM bridge.
RUN apk add --no-cache iproute2-tc

COPY schema.sql /docker-entrypoint-initdb.d/01-schema.sql
COPY network-entrypoint.sh /usr/local/bin/network-entrypoint.sh

ENTRYPOINT ["network-entrypoint.sh"]
CMD ["postgres"]
