# 发布流程

[English](RELEASE.md) · [中文文档导航](README.zh-CN.md)

当前 Python 锁文件目标为 CPython 3.12、Linux x86_64；支持其他 CPU 架构前需重新生成并验证。

1. 同步更新 `VERSION`、`CHANGELOG.md`、服务元数据、Compose 镜像标签与比赛材料。
2. 在可用环境运行两个本地验证入口。
3. 生成并检查确定性源码 SBOM：

```bash
python3 scripts/generate-source-sbom.py --output artifacts/sbom/source.spdx.json
```

4. 构建发布包。打包检查会重新执行测试、打包 Skill、更新正式 PPT 校验值、生成源码 SBOM，并拒绝缺失或受限归档项：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-release.ps1
```

5. 在干净目标主机执行相应版本部署并保留验收包。旧服务器配方为 `sudo ./deploy/bootstrap-server.sh`；当前原生安装应按[原生指南](NATIVE_INSTALL.md)，不要将旧配方验收当作新原生团队完整验收。
6. 基准运行保留所有失败，在看输出前冻结 ground truth，保留独立标注与遥测。
7. 以 `v$(cat VERSION)` 打标签，附服务器 ZIP、校验值、正式 PPT 及校验值、源码 SPDX SBOM、CI 容器 SBOM 和脱敏验收 manifest。
8. 对外主张应对应产物中的证据；未实测的容器／模型性能不填成已验证。

GitHub Actions 和第三方扫描器固定完整提交 SHA；Dependabot 更新也应通过同一套工作流后再更新固定值。
