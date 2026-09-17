package backend

import "testing"

func TestCyberGuardConsoleLocalhost(t *testing.T) {
	d := &DockerBackend{}
	p := d.buildCreatePayload(CreateRequest{}, "8088", 18899)
	binding := p.HostConfig.PortBindings["8088/tcp"]
	if len(binding) != 1 || binding[0].HostIP != "127.0.0.1" || binding[0].HostPort != "18899" {
		t.Fatalf("automatic worker console must bind localhost: %#v", binding)
	}
	p = d.buildCreatePayload(CreateRequest{}, "", 0)
	if p.HostConfig != nil && len(p.HostConfig.PortBindings) != 0 {
		t.Fatal("worker without console must not publish a port")
	}
}
