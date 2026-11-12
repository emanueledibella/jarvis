# Build with the patched Go toolchain and compatible security dependency updates.
# Native build tooling cross-compiles the static proxy for the deployment target.
FROM --platform=$BUILDPLATFORM golang:1.27.3-alpine AS builder
ARG TARGETOS
ARG TARGETARCH
ENV GOTOOLCHAIN=local CGO_ENABLED=0
WORKDIR /build
RUN apk add --no-cache ca-certificates git \
    && go mod init jarvis-proxy \
    && go get github.com/caddyserver/caddy/v2@v2.11.7 \
    && go get golang.org/x/net@v0.60.0 github.com/go-jose/go-jose/v4@v4.1.6
RUN printf 'package main\nimport (\n caddycmd "github.com/caddyserver/caddy/v2/cmd"\n _ "github.com/caddyserver/caddy/v2/modules/standard"\n)\nfunc main() { caddycmd.Main() }\n' >main.go \
    && go mod tidy \
    && GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags='-s -w' -o /out/caddy .

FROM caddy:2.11.7-alpine
USER root
RUN apk upgrade --no-cache \
    && apk del curl \
    && chown -R 10002:10002 /data /config
COPY --from=builder /out/caddy /usr/bin/caddy
USER 10002:10002
