FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/golang:1.25-alpine@sha256:7a00384194cf2cb68924bbb918d675f1517357433c8541bac0ab2f929b9d5447 AS builder
ENV GOPROXY=https://goproxy.cn,direct GOMAXPROCS=4
RUN apk add --no-cache gcc musl-dev
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=1 go build -ldflags '-extldflags "-static"' -o /agentteams-controller ./cmd/controller/
FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-embedded:v1.2.3@sha256:3966dc000f20f98033b15fba897f257186653ef8600e760c1cc55aa620b42bd6
COPY --from=builder /agentteams-controller /usr/local/bin/agentteams-controller
LABEL org.opencontainers.image.revision="223ddc2b8073e4c8b93bcbb15e1d717f196c04d9" io.elsechord.local-patch="automatic-worker-console-hostip-127.0.0.1"
