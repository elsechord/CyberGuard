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
