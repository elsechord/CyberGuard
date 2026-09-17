FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/golang:1.25-alpine@sha256:7a00384194cf2cb68924bbb918d675f1517357433c8541bac0ab2f929b9d5447 AS builder
ARG GOPROXY=https://goproxy.cn,direct
ENV GOPROXY=${GOPROXY} GOMAXPROCS=4
RUN apk add --no-cache gcc musl-dev
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=1 go test ./internal/backend -run TestCyberGuardConsoleLocalhost -count=1
RUN CGO_ENABLED=1 go build -ldflags '-extldflags "-static"' -o /agentteams-controller ./cmd/controller/
FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-embedded:v1.2.2@sha256:c7e467bfa5a2a733ea021c19f223180eef85e3e534873feceb8a7a132253125f
COPY --from=builder /agentteams-controller /usr/local/bin/agentteams-controller
LABEL org.opencontainers.image.source="https://github.com/agentscope-ai/AgentTeams" \
      org.opencontainers.image.revision="849182af8e017168a5a200a87b1062142caf462d" \
      io.elsechord.local-patch="automatic-worker-console-hostip-127.0.0.1"
