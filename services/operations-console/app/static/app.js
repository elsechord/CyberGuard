/* Operations console enhancements: toast + one-time secret copy.
   No inline scripts (strict CSP); everything lives in this file. */
(function () {
  "use strict";

  function showToast(message, tone) {
    var toast = document.getElementById("toast");
    if (!toast) { return; }
    toast.textContent = message;
    toast.style.borderColor = tone === "error" ? "var(--danger)" : "var(--success)";
    toast.hidden = false;
    window.setTimeout(function () { toast.hidden = true; }, 6000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-copy-target]").forEach(function (button) {
      button.addEventListener("click", function () {
        var target = document.getElementById(button.dataset.copyTarget);
        var status = document.getElementById("connection-copy-status");
        var value = target.value === undefined ? target.textContent.trim() : target.value;
        var fallback = function () {
          if (target.select) { target.focus(); target.select(); }
          else {
            var range = document.createRange(); range.selectNodeContents(target);
            var selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
          }
          status.textContent = "请手动复制已选中的文本。";
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(value).then(function () {
            status.textContent = button.dataset.copyTarget === "connection-prompt"
              ? "提示词已复制。请在 Agent 中继续配置与验证。" : "密钥已复制，请保存到本机凭据文件。";
          }, fallback);
        } else { fallback(); }
      });
    });
    var toast = document.getElementById("toast");
    if (toast && toast.getAttribute("data-autoshow") === "1") {
      showToast(toast.getAttribute("data-message") || "", "info");
    }
    var copy = document.getElementById("copy-secret");
    if (copy) {
      copy.addEventListener("click", function () {
        var target = document.getElementById("secret-value");
        var value = target ? target.textContent.trim() : "";
        var done = function () { showToast("API key 已复制到剪贴板。"); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(value).then(done, function () {
            showToast("复制失败，请手动选择文本。", "error");
          });
        } else {
          var range = document.createRange();
          range.selectNodeContents(target);
          var selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          done();
        }
      });
    }
  });
})();
