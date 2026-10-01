const SESSION_STORAGE_KEY = "assistant:session_id";
let chatSessionId = null;
let isLoading = false;
let historyLoaded = false;
let isLoadingHistory = false;

function toggleChat() {
  const panel = document.getElementById("chat-panel");
  const isHidden = panel.classList.contains("hidden");
  if (isHidden) {
    panel.classList.remove("hidden");
    document.getElementById("chat-input").focus();
    if (chatSessionId && !historyLoaded) {
      loadHistory();
    } else {
      scrollToBottom();
    }
  } else {
    panel.classList.add("hidden");
  }
}

function scrollToBottom() {
  const container = document.getElementById("chat-messages");
  if (container) {
    requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }
}

function addMessage(role, content, results, answer) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "flex gap-2" + (role === "user" ? " justify-end" : "");

  if (role === "user") {
    div.innerHTML = `
      <div class="bg-brand-600 text-white rounded-lg px-3 py-2 text-sm max-w-[80%]">${escapeHtml(content)}</div>
    `;
  } else {
    const answerHtml = renderAnswerCard(answer);
    let resultsHtml = "";
    if (results && results.length > 0) {
      resultsHtml = '<div class="mt-1.5 space-y-1">';
      for (const group of results) {
        const total = group.count || group.items.length;
        const more = total > 5 ? ` <span class="font-normal text-surface-400">(${total})</span>` : "";
        resultsHtml += `<div class="text-[10px] font-semibold uppercase tracking-wide text-surface-500 leading-none">${escapeHtml(group.module_name || group.module)}${more}</div>`;
        resultsHtml += '<div class="divide-y divide-surface-100 rounded-md border border-surface-200 bg-white overflow-hidden">';
        for (const item of group.items.slice(0, 5)) {
          const code = item.code ? `<span class="text-[10px] font-normal text-surface-400"> ${escapeHtml(item.code)}</span>` : "";
          const amt = item.amount ? `<span class="shrink-0 text-xs font-semibold tabular-nums text-surface-700">₱${escapeHtml(item.amount)}</span>` : "";
          resultsHtml += `
            <a href="${item.link || '#'}" class="flex items-center justify-between gap-2 px-2 py-1 hover:bg-brand-50 transition" title="${escapeHtml([item.code, item.date, item.status, item.by].filter(Boolean).join(' · '))}">
              <span class="min-w-0 truncate text-xs leading-none text-surface-800">${escapeHtml(item.name || '')}${code}</span>
              ${amt}
            </a>
          `;
        }
        resultsHtml += "</div>";
      }
      resultsHtml += "</div>";
    }
    div.innerHTML = `
      <div class="flex-shrink-0 h-7 w-7 rounded-full bg-brand-100 flex items-center justify-center">
        <svg class="h-4 w-4 text-brand-600" aria-hidden="true"><use href="#i-chat"/></svg>
      </div>
      <div class="w-fit min-w-0 max-w-[80%]">
        <div class="bg-surface-100 rounded-lg px-3 py-2 text-sm text-surface-700 whitespace-pre-wrap break-words">${escapeHtml(content)}</div>
        <div class="text-sm text-surface-700">${answerHtml}${resultsHtml}</div>
      </div>
    `;
  }

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function renderAnswerCard(answer) {
  if (!answer || typeof answer !== "object") return "";
  const metrics = answer.metrics || [];
  const rows = answer.rows || [];
  const links = answer.links || [];
  let html = '<div class="mt-2 rounded-lg border border-brand-200 bg-brand-50 p-3 space-y-2">';
  if (answer.title) {
    html += `<div class="text-xs font-semibold text-brand-700 uppercase tracking-wide">${escapeHtml(answer.title)}</div>`;
  }
  if (metrics.length > 0) {
    html += '<div class="flex flex-wrap gap-1.5">';
    for (const m of metrics.slice(0, 6)) {
      html += `<div class="rounded-md bg-white border border-surface-200 px-2 py-1">
        <div class="text-[10px] uppercase tracking-wide text-surface-400">${escapeHtml(m.label || "")}</div>
        <div class="text-sm font-semibold text-surface-900">${escapeHtml(String(m.value ?? ""))}</div>
      </div>`;
    }
    html += "</div>";
  }
  if (rows.length > 0) {
    const keys = Object.keys(rows[0] || {});
    html += '<div class="overflow-x-auto rounded-md bg-white border border-surface-200"><table class="w-full text-xs">';
    html += `<thead><tr>${keys.map((k) => `<th class="px-2 py-1 text-left font-semibold text-surface-500">${escapeHtml(k)}</th>`).join("")}</tr></thead>`;
    html += "<tbody>";
    for (const r of rows.slice(0, 8)) {
      html += `<tr>${keys.map((k) => `<td class="px-2 py-1 text-surface-700 whitespace-pre-wrap">${escapeHtml(String(r[k] ?? ""))}</td>`).join("")}</tr>`;
    }
    html += "</tbody></table></div>";
  }
  if (links.length > 0) {
    html += '<div class="flex flex-col gap-0.5">';
    for (const l of links.slice(0, 4)) {
      const href = String(l.url || "#").replace(/"/g, "&quot;");
      html += `<a href="${href}" class="text-xs text-brand-600 hover:underline">${escapeHtml(l.label || l.url)}</a>`;
    }
    html += "</div>";
  }
  if (answer.note) {
    html += `<div class="text-xs text-surface-500 italic">${escapeHtml(answer.note)}</div>`;
  }
  html += "</div>";
  return html;
}

function showTyping() {
  document.getElementById("chat-typing").classList.remove("hidden");
  const container = document.getElementById("chat-messages");
  container.scrollTop = container.scrollHeight;
}

function hideTyping() {
  document.getElementById("chat-typing").classList.add("hidden");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function sendMessage(message) {
  if (!message.trim() || isLoading) return;

  isLoading = true;
  addMessage("user", message);
  document.getElementById("chat-input").value = "";
  showTyping();

  try {
    const response = await fetch("/assistant/chat/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.querySelector("[name=csrf-token]").content,
      },
      body: JSON.stringify({ message, session_id: chatSessionId }),
    });

    const data = await response.json();
    chatSessionId = data.session_id;
    localStorage.setItem(SESSION_STORAGE_KEY, chatSessionId);
    historyLoaded = true;
    addMessage("assistant", data.text, data.results, data.answer_block);
  } catch (error) {
    addMessage("assistant", "An error occurred. Please try again.", []);
  } finally {
    isLoading = false;
    hideTyping();
  }
}

function sendSuggestion(text) {
  sendMessage(text);
}

function clearChat() {
  if (confirm("Clear conversation history?")) {
    document.getElementById("chat-messages").innerHTML = "";
    chatSessionId = null;
    historyLoaded = false;
    localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

async function loadHistory() {
  if (isLoadingHistory) return;
  isLoadingHistory = true;
  try {
    const response = await fetch(`/assistant/chat/?session_id=${chatSessionId}`);
    const data = await response.json();
    if (data.messages && data.messages.length > 0) {
      const container = document.getElementById("chat-messages");
      container.innerHTML = "";
      for (const msg of data.messages) {
        addMessage(msg.role, msg.content, msg.results, msg.answer);
      }
    }
    historyLoaded = true;
    scrollToBottom();
  } catch (error) {
    console.error("Failed to load history:", error);
  } finally {
    isLoadingHistory = false;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("chat-form");
  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const input = document.getElementById("chat-input");
      sendMessage(input.value);
    });
  }

  const saved = localStorage.getItem(SESSION_STORAGE_KEY);
  if (saved) {
    chatSessionId = saved;
    loadHistory();
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      const panel = document.getElementById("chat-panel");
      if (!panel.classList.contains("hidden")) {
        toggleChat();
      }
    }
  });
});
