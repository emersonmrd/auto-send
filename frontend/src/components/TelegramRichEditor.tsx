"use client";

import React, { useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  Bold,
  Code,
  EyeOff,
  FileCode,
  Italic,
  Link2,
  Quote,
  RemoveFormatting,
  Strikethrough,
  Trash2,
  Underline,
} from "lucide-react";

export function escapeHtmlText(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function escapeHtmlAttr(raw: string): string {
  return escapeHtmlText(raw).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function unescapeHtmlEntities(raw: string): string {
  return raw
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&#x27;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&");
}

export function normalizeTelegramLinkUrl(rawInput: string): {
  ok: boolean;
  url?: string;
  error?: string;
} {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return { ok: false, error: "Informe a URL de destino." };
  }
  if (/^http:\/\//i.test(trimmed)) {
    return { ok: false, error: "Use um endereço https://" };
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed) && !/^https:\/\//i.test(trimmed)) {
    return { ok: false, error: "Use um endereço https://" };
  }
  const candidate = /^https:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "https:" || !parsed.hostname) {
      return { ok: false, error: "Use um endereço https://" };
    }
    return { ok: true, url: candidate };
  } catch {
    return { ok: false, error: "Use um endereço https://" };
  }
}

// Converte HTML do Telegram em HTML seguro para o contentEditable (com atributos visuais)
export function telegramHtmlToEditableHtml(telegramHtml: string): string {
  if (!telegramHtml) return "";

  const tagRegex = /<\/?[a-zA-Z][a-zA-Z0-9-]*(\s+[^>]*)?>/g;
  const parts: string[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  const pushText = (segment: string) => {
    const normalized = escapeHtmlText(unescapeHtmlEntities(segment)).replace(
      /\n/g,
      "<br>"
    );
    parts.push(normalized);
  };

  while ((match = tagRegex.exec(telegramHtml)) !== null) {
    if (match.index > lastIdx) {
      pushText(telegramHtml.slice(lastIdx, match.index));
    }
    const token = match[0];
    const inner = token.slice(1, -1).trim();

    if (inner.startsWith("/")) {
      const closeName = inner.slice(1).trim().toLowerCase();
      if (closeName === "strong") parts.push("</b>");
      else if (closeName === "em") parts.push("</i>");
      else if (closeName === "ins") parts.push("</u>");
      else if (closeName === "strike" || closeName === "del") parts.push("</s>");
      else if (closeName === "tg-spoiler" || closeName === "span") {
        parts.push("</span>");
      } else if (
        ["b", "i", "u", "s", "code", "pre", "blockquote", "a"].includes(
          closeName
        )
      ) {
        parts.push(`</${closeName}>`);
      } else {
        pushText(token);
      }
    } else {
      const lower = inner.toLowerCase();
      if (lower === "b" || lower === "strong") parts.push("<b>");
      else if (lower === "i" || lower === "em") parts.push("<i>");
      else if (lower === "u" || lower === "ins") parts.push("<u>");
      else if (lower === "s" || lower === "strike" || lower === "del") {
        parts.push("<s>");
      } else if (lower === "code") {
        parts.push('<code class="font-mono bg-[#17212b] px-1 rounded text-[#90caf9]">');
      } else if (lower === "pre") {
        parts.push(
          '<pre class="font-mono bg-[#17212b] p-1.5 rounded text-xs text-[#90caf9] my-0.5">'
        );
      } else if (lower === "blockquote") {
        parts.push(
          '<blockquote class="border-l-2 border-[#5288c1] pl-2 my-0.5 italic text-gray-200">'
        );
      } else if (
        lower === "tg-spoiler" ||
        lower === 'span class="tg-spoiler"' ||
        lower === "span class='tg-spoiler'"
      ) {
        parts.push(
          '<span data-tg-spoiler="true" class="bg-gray-600/50 border border-dashed border-gray-400/60 rounded px-1">'
        );
      } else {
        const anchorMatch = /^a\s+href=(?:"([^"]*)"|'([^']*)')$/i.exec(inner);
        if (anchorMatch) {
          const rawHref = unescapeHtmlEntities(
            anchorMatch[1] ?? anchorMatch[2] ?? ""
          );
          const safeHref = escapeHtmlAttr(rawHref);
          parts.push(
            `<a href="${safeHref}" data-tg-href="${safeHref}" class="text-[#64b5f6] underline font-medium cursor-pointer">`
          );
        } else {
          pushText(token);
        }
      }
    }
    lastIdx = match.index + token.length;
  }

  if (lastIdx < telegramHtml.length) {
    pushText(telegramHtml.slice(lastIdx));
  }

  return parts.join("");
}

// Serializa a árvore DOM do contentEditable para o HTML canônico do Telegram
export function serializeDomToTelegramHtml(root: Node): string {
  const serializeChildren = (parent: Node): string => {
    const out: string[] = [];
    parent.childNodes.forEach((child) => {
      out.push(serializeNode(child));
    });
    return out.join("");
  };

  const serializeNode = (node: Node): string => {
    if (node.nodeType === Node.TEXT_NODE) {
      return escapeHtmlText((node.nodeValue || "").replace(/\u00a0/g, " ").replace(/\u200b/gi, ""));
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return "";
    }
    const el = node as HTMLElement;
    const tag = el.tagName.toLowerCase();

    if (tag === "br") {
      return "\n";
    }

    const inner = serializeChildren(el);

    if (tag === "b" || tag === "strong") {
      return inner ? `<b>${inner}</b>` : "";
    }
    if (tag === "i" || tag === "em") {
      return inner ? `<i>${inner}</i>` : "";
    }
    if (tag === "u" || tag === "ins") {
      return inner ? `<u>${inner}</u>` : "";
    }
    if (tag === "s" || tag === "strike" || tag === "del") {
      return inner ? `<s>${inner}</s>` : "";
    }
    if (tag === "code") {
      return inner ? `<code>${inner}</code>` : "";
    }
    if (tag === "pre") {
      return inner ? `<pre>${inner}</pre>` : "";
    }
    if (tag === "blockquote") {
      return inner ? `<blockquote>${inner}</blockquote>` : "";
    }
    if (
      tag === "tg-spoiler" ||
      el.getAttribute("data-tg-spoiler") === "true" ||
      el.classList.contains("tg-spoiler")
    ) {
      return inner ? `<tg-spoiler>${inner}</tg-spoiler>` : "";
    }
    if (tag === "a") {
      const href =
        el.getAttribute("data-tg-href") || el.getAttribute("href") || "";
      if (!href || !inner) return inner;
      return `<a href="${escapeHtmlAttr(href)}">${inner}</a>`;
    }
    if (tag === "div" || tag === "p") {
      const prev = el.previousSibling;
      const prefix = prev ? "\n" : "";
      return `${prefix}${inner.replace(/\n$/, "")}`;
    }

    return inner;
  };

  return serializeChildren(root).replace(/\n+$/, (m) =>
    m.length > 1 ? m.slice(0, -1) : ""
  );
}

function SpoilerPreviewSpan({ children }: { children: React.ReactNode }) {
  const [revealed, setRevealed] = useState(false);
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        setRevealed((v) => !v);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setRevealed((v) => !v);
        }
      }}
      title={revealed ? "Ocultar spoiler" : "Clique para revelar spoiler"}
      data-testid="telegram-spoiler-preview"
      data-revealed={revealed ? "true" : "false"}
      className={`rounded px-1 transition cursor-pointer ${
        revealed
          ? "bg-gray-600/30 text-gray-100"
          : "bg-gray-400/40 text-transparent blur-[4px] select-none"
      }`}
    >
      {children}
    </span>
  );
}

// Renderiza o HTML do Telegram no balão de preview e nos cards da fila
export function renderTelegramHtmlPreview(rawText: string): React.ReactNode {
  if (!rawText || !rawText.trim()) {
    return (
      <span className="text-gray-300 italic">Digite uma mensagem abaixo...</span>
    );
  }

  type Token =
    | { type: "text"; value: string }
    | { type: "open"; tag: string; href?: string }
    | { type: "close"; tag: string };

  const tokens: Token[] = [];
  const tagRegex = /<\/?[a-zA-Z][a-zA-Z0-9-]*(\s+[^>]*)?>/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = tagRegex.exec(rawText)) !== null) {
    if (match.index > lastIdx) {
      tokens.push({
        type: "text",
        value: unescapeHtmlEntities(rawText.slice(lastIdx, match.index)),
      });
    }
    const token = match[0];
    const inner = token.slice(1, -1).trim();
    if (inner.startsWith("/")) {
      const rawName = inner.slice(1).trim().toLowerCase();
      const normName =
        rawName === "strong"
          ? "b"
          : rawName === "em"
            ? "i"
            : rawName === "ins"
              ? "u"
              : rawName === "strike" || rawName === "del"
                ? "s"
                : rawName === "span"
                  ? "tg-spoiler"
                  : rawName;
      tokens.push({ type: "close", tag: normName });
    } else {
      const lower = inner.toLowerCase();
      if (lower === "b" || lower === "strong") {
        tokens.push({ type: "open", tag: "b" });
      } else if (lower === "i" || lower === "em") {
        tokens.push({ type: "open", tag: "i" });
      } else if (lower === "u" || lower === "ins") {
        tokens.push({ type: "open", tag: "u" });
      } else if (lower === "s" || lower === "strike" || lower === "del") {
        tokens.push({ type: "open", tag: "s" });
      } else if (lower === "code") {
        tokens.push({ type: "open", tag: "code" });
      } else if (lower === "pre") {
        tokens.push({ type: "open", tag: "pre" });
      } else if (lower === "blockquote") {
        tokens.push({ type: "open", tag: "blockquote" });
      } else if (
        lower === "tg-spoiler" ||
        lower === 'span class="tg-spoiler"' ||
        lower === "span class='tg-spoiler'"
      ) {
        tokens.push({ type: "open", tag: "tg-spoiler" });
      } else {
        const anchorMatch = /^a\s+href=(?:"([^"]*)"|'([^']*)')$/i.exec(inner);
        if (anchorMatch) {
          const href = unescapeHtmlEntities(
            anchorMatch[1] ?? anchorMatch[2] ?? ""
          );
          tokens.push({ type: "open", tag: "a", href });
        } else {
          tokens.push({ type: "text", value: unescapeHtmlEntities(token) });
        }
      }
    }
    lastIdx = match.index + token.length;
  }

  if (lastIdx < rawText.length) {
    tokens.push({
      type: "text",
      value: unescapeHtmlEntities(rawText.slice(lastIdx)),
    });
  }

  type Frame = { tag: string; href?: string; children: React.ReactNode[] };
  const stack: Frame[] = [{ tag: "root", children: [] }];
  let keyCounter = 0;

  const wrapFrame = (frame: Frame): React.ReactNode => {
    const key = `tg-node-${keyCounter++}`;
    switch (frame.tag) {
      case "b":
        return <strong key={key}>{frame.children}</strong>;
      case "i":
        return <em key={key}>{frame.children}</em>;
      case "u":
        return <u key={key}>{frame.children}</u>;
      case "s":
        return <s key={key}>{frame.children}</s>;
      case "code":
        return (
          <code
            key={key}
            className="font-mono bg-[#0e1621]/80 px-1 py-0.5 rounded text-xs text-[#90caf9]"
          >
            {frame.children}
          </code>
        );
      case "pre":
        return (
          <pre
            key={key}
            className="font-mono bg-[#0e1621]/90 p-2 rounded-lg text-xs text-[#90caf9] overflow-x-auto my-1"
          >
            {frame.children}
          </pre>
        );
      case "blockquote":
        return (
          <blockquote
            key={key}
            className="border-l-2 border-[#64b5f6] pl-2.5 my-1 text-gray-200 italic bg-[#17212b]/40 py-0.5 rounded-r"
          >
            {frame.children}
          </blockquote>
        );
      case "tg-spoiler":
        return <SpoilerPreviewSpan key={key}>{frame.children}</SpoilerPreviewSpan>;
      case "a":
        return (
          <a
            key={key}
            href={frame.href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#64b5f6] hover:text-[#90caf9] underline font-medium cursor-pointer"
            onClick={(e) => e.stopPropagation()}
          >
            {frame.children}
          </a>
        );
      default:
        return <React.Fragment key={key}>{frame.children}</React.Fragment>;
    }
  };

  for (const tok of tokens) {
    if (tok.type === "text") {
      stack[stack.length - 1].children.push(tok.value);
    } else if (tok.type === "open") {
      stack.push({ tag: tok.tag, href: tok.href, children: [] });
    } else if (tok.type === "close") {
      if (stack.length > 1 && stack[stack.length - 1].tag === tok.tag) {
        const closed = stack.pop()!;
        stack[stack.length - 1].children.push(wrapFrame(closed));
      }
    }
  }

  while (stack.length > 1) {
    const closed = stack.pop()!;
    stack[stack.length - 1].children.push(wrapFrame(closed));
  }

  return stack[0].children;
}

export interface TelegramRichEditorHandle {
  openLinkModal: () => void;
}

interface TelegramRichEditorProps {
  id?: string;
  ariaLabel: string;
  placeholder: string;
  value: string;
  onChange: (newTelegramHtml: string) => void;
  minRows?: number;
  editorRefHandle?: React.Ref<TelegramRichEditorHandle>;
}

export function TelegramRichEditor({
  id,
  ariaLabel,
  placeholder,
  value,
  onChange,
  minRows = 2,
  editorRefHandle,
}: TelegramRichEditorProps) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const lastSerializedRef = useRef<string>("");
  const savedRangeRef = useRef<Range | null>(null);
  const editingAnchorRef = useRef<HTMLAnchorElement | null>(null);

  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkWord, setLinkWord] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const [isEditingExistingLink, setIsEditingExistingLink] = useState(false);

  const [activeStyles, setActiveStyles] = useState({
    bold: false,
    italic: false,
    underline: false,
    strike: false,
    code: false,
    pre: false,
    blockquote: false,
    spoiler: false,
    link: false,
  });

  const updateActiveStyles = () => {
    const el = editorRef.current;
    if (!el) return;

    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) {
      setActiveStyles({
        bold: false,
        italic: false,
        underline: false,
        strike: false,
        code: false,
        pre: false,
        blockquote: false,
        spoiler: false,
        link: false,
      });
      return;
    }

    const range = sel.getRangeAt(0);
    if (!el.contains(range.commonAncestorContainer)) {
      setActiveStyles({
        bold: false,
        italic: false,
        underline: false,
        strike: false,
        code: false,
        pre: false,
        blockquote: false,
        spoiler: false,
        link: false,
      });
      return;
    }

    const newStyles = {
      bold: false,
      italic: false,
      underline: false,
      strike: false,
      code: false,
      pre: false,
      blockquote: false,
      spoiler: false,
      link: false,
    };

    let curr: Node | null = range.commonAncestorContainer;
    if (curr === el && sel.anchorNode && el.contains(sel.anchorNode)) {
      curr = sel.anchorNode;
    }

    while (curr && curr !== el) {
      if (curr.nodeType === Node.ELEMENT_NODE) {
        const elem = curr as HTMLElement;
        const tag = elem.tagName.toLowerCase();
        if (tag === "b" || tag === "strong") newStyles.bold = true;
        if (tag === "i" || tag === "em") newStyles.italic = true;
        if (tag === "u" || tag === "ins") newStyles.underline = true;
        if (tag === "s" || tag === "strike" || tag === "del") newStyles.strike = true;
        if (tag === "pre") newStyles.pre = true;
        if (tag === "code" && !newStyles.pre) newStyles.code = true;
        if (tag === "blockquote") newStyles.blockquote = true;
        if (
          tag === "tg-spoiler" ||
          elem.getAttribute("data-tg-spoiler") === "true" ||
          elem.classList.contains("tg-spoiler")
        ) {
          newStyles.spoiler = true;
        }
        if (tag === "a") newStyles.link = true;
      }
      curr = curr.parentNode;
    }

    setActiveStyles((prev) => {
      if (
        prev.bold === newStyles.bold &&
        prev.italic === newStyles.italic &&
        prev.underline === newStyles.underline &&
        prev.strike === newStyles.strike &&
        prev.code === newStyles.code &&
        prev.pre === newStyles.pre &&
        prev.blockquote === newStyles.blockquote &&
        prev.spoiler === newStyles.spoiler &&
        prev.link === newStyles.link
      ) {
        return prev;
      }
      return newStyles;
    });
  };

  useEffect(() => {
    const handleSelection = () => {
      updateActiveStyles();
    };
    document.addEventListener("selectionchange", handleSelection);
    return () => {
      document.removeEventListener("selectionchange", handleSelection);
    };
  }, []);

  // Sincroniza value externo com o DOM do contentEditable
  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    if (value === lastSerializedRef.current) return;
    lastSerializedRef.current = value;
    el.innerHTML = telegramHtmlToEditableHtml(value);
    updateActiveStyles();
  }, [value]);

  const emitChangeFromDom = () => {
    const el = editorRef.current;
    if (!el) return;
    const serialized = serializeDomToTelegramHtml(el);
    lastSerializedRef.current = serialized;
    onChange(serialized);
    updateActiveStyles();
  };

  const findClosestTag = (
    node: Node | null,
    tagName: string
  ): HTMLElement | null => {
    let curr: Node | null = node;
    const root = editorRef.current;
    while (curr && curr !== root) {
      if (
        curr.nodeType === Node.ELEMENT_NODE &&
        (curr as HTMLElement).tagName.toLowerCase() === tagName.toLowerCase()
      ) {
        return curr as HTMLElement;
      }
      curr = curr.parentNode;
    }
    return null;
  };

  const applyWrapTag = (
    tagName: string,
    attrs?: Record<string, string>
  ) => {
    const el = editorRef.current;
    if (!el) return;
    el.focus();

    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (!el.contains(range.commonAncestorContainer)) return;

    // Se já estiver dentro da mesma tag, remove a formatação (toggle)
    const existing =
      tagName === "span" && attrs?.["data-tg-spoiler"] === "true"
        ? (() => {
            let curr: Node | null = range.commonAncestorContainer;
            while (curr && curr !== el) {
              if (
                curr.nodeType === Node.ELEMENT_NODE &&
                (curr as HTMLElement).getAttribute("data-tg-spoiler") === "true"
              ) {
                return curr as HTMLElement;
              }
              curr = curr.parentNode;
            }
            return null;
          })()
        : findClosestTag(range.commonAncestorContainer, tagName);

    if (existing) {
      const parent = existing.parentNode;
      if (parent) {
        while (existing.firstChild) {
          parent.insertBefore(existing.firstChild, existing);
        }
        parent.removeChild(existing);
        emitChangeFromDom();
      }
      return;
    }

    const selectedText = range.toString();
    const wrapper = document.createElement(tagName);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        wrapper.setAttribute(k, v);
      }
    }

    if (selectedText) {
      const contents = range.extractContents();
      wrapper.appendChild(contents);
      range.insertNode(wrapper);
      sel.removeAllRanges();
      const newRange = document.createRange();
      newRange.selectNodeContents(wrapper);
      sel.addRange(newRange);
    } else {
      if (tagName === "pre") {
        // Sem seleção: insere bloco de código no ponto do cursor com quebra de linha inicial para digitação
        wrapper.appendChild(document.createElement("br"));
        range.insertNode(wrapper);
        sel.removeAllRanges();
        const newRange = document.createRange();
        newRange.setStart(wrapper, 0);
        newRange.collapse(true);
        sel.addRange(newRange);
      } else {
        // Sem seleção: insere tag no ponto do cursor com nó de texto de largura zero para digitação imediata
        const placeholder = document.createTextNode("\u200B");
        wrapper.appendChild(placeholder);
        range.insertNode(wrapper);
        sel.removeAllRanges();
        const newRange = document.createRange();
        newRange.setStart(placeholder, 1);
        newRange.collapse(true);
        sel.addRange(newRange);
      }
    }

    emitChangeFromDom();
  };

  const openLinkModalFromSelection = () => {
    const el = editorRef.current;
    setLinkError(null);
    editingAnchorRef.current = null;
    savedRangeRef.current = null;

    if (el) {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        if (el.contains(range.commonAncestorContainer)) {
          const anchor = findClosestTag(
            range.commonAncestorContainer,
            "a"
          ) as HTMLAnchorElement | null;
          if (anchor) {
            editingAnchorRef.current = anchor;
            setIsEditingExistingLink(true);
            setLinkWord(anchor.textContent || "");
            setLinkUrl(
              anchor.getAttribute("data-tg-href") ||
                anchor.getAttribute("href") ||
                ""
            );
            setShowLinkModal(true);
            return;
          }
          savedRangeRef.current = range.cloneRange();
          setIsEditingExistingLink(false);
          setLinkWord(range.toString());
          setLinkUrl("");
          setShowLinkModal(true);
          return;
        }
      }
    }

    setIsEditingExistingLink(false);
    setLinkWord("");
    setLinkUrl("");
    setShowLinkModal(true);
  };

  useImperativeHandle(editorRefHandle, () => ({
    openLinkModal: openLinkModalFromSelection,
  }));

  const handleEditorClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const anchor = findClosestTag(target, "a") as HTMLAnchorElement | null;
    if (anchor) {
      e.preventDefault();
      editingAnchorRef.current = anchor;
      savedRangeRef.current = null;
      setLinkError(null);
      setIsEditingExistingLink(true);
      setLinkWord(anchor.textContent || "");
      setLinkUrl(
        anchor.getAttribute("data-tg-href") || anchor.getAttribute("href") || ""
      );
      setShowLinkModal(true);
    }
  };

  const handleConfirmLinkModal = () => {
    const word = linkWord.trim();
    if (!word) {
      setLinkError("Informe a palavra ou texto a ser exibido.");
      return;
    }
    const normalized = normalizeTelegramLinkUrl(linkUrl);
    if (!normalized.ok || !normalized.url) {
      setLinkError(normalized.error || "Use um endereço https://");
      return;
    }

    const safeUrl = normalized.url;
    const el = editorRef.current;
    if (!el) return;

    if (editingAnchorRef.current && el.contains(editingAnchorRef.current)) {
      const anchor = editingAnchorRef.current;
      anchor.setAttribute("href", safeUrl);
      anchor.setAttribute("data-tg-href", safeUrl);
      anchor.textContent = word;
    } else {
      const anchor = document.createElement("a");
      anchor.setAttribute("href", safeUrl);
      anchor.setAttribute("data-tg-href", safeUrl);
      anchor.className =
        "text-[#64b5f6] underline font-medium cursor-pointer";
      anchor.textContent = word;

      if (savedRangeRef.current && el.contains(savedRangeRef.current.commonAncestorContainer)) {
        const range = savedRangeRef.current;
        range.deleteContents();
        range.insertNode(anchor);
      } else {
        el.appendChild(anchor);
      }
    }

    setShowLinkModal(false);
    editingAnchorRef.current = null;
    savedRangeRef.current = null;
    emitChangeFromDom();
  };

  const handleRemoveLink = () => {
    const el = editorRef.current;
    const anchor = editingAnchorRef.current;
    if (el && anchor && el.contains(anchor)) {
      const textNode = document.createTextNode(anchor.textContent || "");
      anchor.parentNode?.replaceChild(textNode, anchor);
      emitChangeFromDom();
    }
    setShowLinkModal(false);
    editingAnchorRef.current = null;
    savedRangeRef.current = null;
  };

  const handleClearFormatting = () => {
    const el = editorRef.current;
    if (!el) return;
    el.focus();

    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (!el.contains(range.commonAncestorContainer)) return;

    const formattingTagNames = new Set([
      "b",
      "strong",
      "i",
      "em",
      "u",
      "ins",
      "s",
      "strike",
      "del",
      "code",
      "pre",
      "blockquote",
      "span",
      "a",
    ]);

    if (!range.collapsed && range.toString()) {
      const text = range.toString();
      range.deleteContents();

      const fragment = document.createDocumentFragment();
      const lines = text.split("\n");
      lines.forEach((line, idx) => {
        if (line) {
          fragment.appendChild(document.createTextNode(line));
        }
        if (idx < lines.length - 1) {
          fragment.appendChild(document.createElement("br"));
        }
      });
      range.insertNode(fragment);

      let curr: Node | null = range.commonAncestorContainer;
      while (curr && curr !== el) {
        if (curr.nodeType === Node.ELEMENT_NODE) {
          const elem = curr as HTMLElement;
          const tag = elem.tagName.toLowerCase();
          const isSpoiler =
            tag === "span" && elem.getAttribute("data-tg-spoiler") === "true";
          if (formattingTagNames.has(tag) || isSpoiler) {
            const parent = elem.parentNode;
            if (parent) {
              while (elem.firstChild) {
                parent.insertBefore(elem.firstChild, elem);
              }
              parent.removeChild(elem);
            }
          }
        }
        curr = curr.parentNode;
      }

      const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT);
      const toRemove: Element[] = [];
      while (walker.nextNode()) {
        const item = walker.currentNode as HTMLElement;
        const tag = item.tagName.toLowerCase();
        if (
          formattingTagNames.has(tag) &&
          !item.textContent?.trim() &&
          !item.querySelector("br")
        ) {
          toRemove.push(item);
        }
      }
      toRemove.forEach((item) => item.parentNode?.removeChild(item));
    } else {
      let curr: Node | null = range.commonAncestorContainer;
      while (curr && curr !== el) {
        if (curr.nodeType === Node.ELEMENT_NODE) {
          const elem = curr as HTMLElement;
          const tag = elem.tagName.toLowerCase();
          const isSpoiler =
            tag === "span" && elem.getAttribute("data-tg-spoiler") === "true";
          if (formattingTagNames.has(tag) || isSpoiler) {
            const parent = elem.parentNode;
            if (parent) {
              while (elem.firstChild) {
                parent.insertBefore(elem.firstChild, elem);
              }
              parent.removeChild(elem);
              break;
            }
          }
        }
        curr = curr.parentNode;
      }
    }

    emitChangeFromDom();
    updateActiveStyles();
  };

  const getToolbarButtonClass = (isActive: boolean) =>
    `p-1 rounded transition border ${
      isActive
        ? "bg-[#5288c1]/30 text-[#90caf9] font-medium border-[#5288c1]/50 shadow-sm"
        : "border-transparent text-gray-300 hover:text-white hover:bg-[#17212b]"
    }`;

  const isCursorAtEndOfPre = (pre: HTMLElement, range: Range): boolean => {
    const testRange = document.createRange();
    testRange.setStart(range.endContainer, range.endOffset);
    testRange.setEndAfter(pre.lastChild || pre);
    const remaining = testRange.toString();
    return remaining === "" || remaining === "\n";
  };

  const isCursorAtStartOfPre = (pre: HTMLElement, range: Range): boolean => {
    const beforeRange = document.createRange();
    beforeRange.setStartBefore(pre.firstChild || pre);
    beforeRange.setEnd(range.startContainer, range.startOffset);
    return beforeRange.toString() === "";
  };

  const isCursorOnEmptyLineAtEndOfPre = (pre: HTMLElement, range: Range): boolean => {
    // 1. Verifica se não há texto substantivo após o cursor no pre
    const testRange = document.createRange();
    testRange.setStart(range.endContainer, range.endOffset);
    testRange.setEndAfter(pre.lastChild || pre);
    if (testRange.toString().trim() !== "") {
      return false;
    }

    // 2. Se o pre está completamente vazio
    const preText = pre.textContent || "";
    if (preText.trim() === "") {
      return true;
    }

    // 3. Caso o cursor esteja no container pre (ex.: Chromium insere <br> e coloca o cursor entre BRs)
    if (range.startContainer === pre) {
      const prevChild = range.startOffset > 0 ? pre.childNodes[range.startOffset - 1] : null;
      if (!prevChild || (prevChild.nodeType === Node.ELEMENT_NODE && (prevChild as HTMLElement).tagName.toLowerCase() === "br")) {
        return true;
      }
    }

    // 4. Caso o cursor esteja em um nó de texto
    if (range.startContainer.nodeType === Node.TEXT_NODE) {
      const val = range.startContainer.nodeValue || "";
      const textBefore = val.slice(0, range.startOffset);
      if (textBefore.endsWith("\n")) {
        return true;
      }
      if (range.startOffset === 0) {
        let prev = range.startContainer.previousSibling;
        while (prev && prev.nodeType === Node.TEXT_NODE && prev.nodeValue === "") {
          prev = prev.previousSibling;
        }
        if (!prev || (prev.nodeType === Node.ELEMENT_NODE && (prev as HTMLElement).tagName.toLowerCase() === "br")) {
          return true;
        }
      }
    }

    return false;
  };

  const exitPreBlock = (pre: HTMLElement, removeTrailingNewline: boolean) => {
    const root = editorRef.current;
    if (!root) return;

    const sel = window.getSelection();
    if (!sel) return;

    if (removeTrailingNewline) {
      // Remove elementos <br> residuais no final do pre
      while (
        pre.lastChild &&
        pre.lastChild.nodeType === Node.ELEMENT_NODE &&
        (pre.lastChild as HTMLElement).tagName.toLowerCase() === "br"
      ) {
        pre.removeChild(pre.lastChild);
      }

      // Remove \n no final do último nó de texto
      const walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT);
      let lastTextNode: Text | null = null;
      while (walker.nextNode()) {
        lastTextNode = walker.currentNode as Text;
      }
      if (lastTextNode && lastTextNode.nodeValue) {
        while (lastTextNode.nodeValue.endsWith("\n")) {
          lastTextNode.nodeValue = lastTextNode.nodeValue.slice(0, -1);
        }
        if (lastTextNode.nodeValue === "" && pre.childNodes.length > 1) {
          lastTextNode.parentNode?.removeChild(lastTextNode);
        }
      }
    }

    let targetNode = pre.nextSibling as HTMLElement | null;
    if (!targetNode) {
      const newLine = document.createElement("div");
      newLine.appendChild(document.createElement("br"));
      pre.parentNode?.insertBefore(newLine, pre.nextSibling);
      targetNode = newLine;
    } else if (targetNode.tagName && targetNode.tagName.toLowerCase() === "br") {
      const next = targetNode.nextSibling;
      if (!next) {
        const newLine = document.createElement("div");
        newLine.appendChild(document.createElement("br"));
        pre.parentNode?.replaceChild(newLine, targetNode);
        targetNode = newLine;
      } else {
        const newRange = document.createRange();
        newRange.setStart(next, 0);
        newRange.collapse(true);
        sel.removeAllRanges();
        sel.addRange(newRange);
        emitChangeFromDom();
        return;
      }
    }

    const newRange = document.createRange();
    if (targetNode.nodeType === Node.TEXT_NODE) {
      newRange.setStart(targetNode, 0);
    } else if (targetNode.firstChild) {
      newRange.setStart(targetNode, 0);
    } else {
      newRange.selectNodeContents(targetNode);
    }
    newRange.collapse(true);

    sel.removeAllRanges();
    sel.addRange(newRange);
    emitChangeFromDom();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.metaKey) {
      const key = e.key.toLowerCase();
      if (key === "b") {
        e.preventDefault();
        applyWrapTag("b");
        return;
      } else if (key === "i") {
        e.preventDefault();
        applyWrapTag("i");
        return;
      } else if (key === "u") {
        e.preventDefault();
        applyWrapTag("u");
        return;
      } else if (e.key === "Enter") {
        // Atalho Ctrl+Enter / Cmd+Enter: sai do bloco de código imediatamente
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const range = sel.getRangeAt(0);
          const pre = findClosestTag(range.commonAncestorContainer, "pre");
          if (pre) {
            e.preventDefault();
            exitPreBlock(pre, false);
            return;
          }
        }
      }
    }

    if (e.key === "Enter") {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const pre = findClosestTag(range.commonAncestorContainer, "pre");
        if (pre) {
          if (isCursorOnEmptyLineAtEndOfPre(pre, range)) {
            // Enter duplo em linha vazia no final do bloco: sai do bloco de código
            e.preventDefault();
            exitPreBlock(pre, true);
            return;
          }
        }
      }
    }

    if (e.key === "ArrowDown") {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const pre = findClosestTag(range.commonAncestorContainer, "pre");
        if (pre && range.collapsed && isCursorAtEndOfPre(pre, range)) {
          e.preventDefault();
          exitPreBlock(pre, false);
          return;
        }
      }
    }

    if (e.key === "ArrowUp") {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const pre = findClosestTag(range.commonAncestorContainer, "pre");
        if (pre && range.collapsed && isCursorAtStartOfPre(pre, range)) {
          e.preventDefault();
          const root = editorRef.current;
          if (pre.previousSibling) {
            const prev = pre.previousSibling as HTMLElement;
            const newRange = document.createRange();
            newRange.selectNodeContents(prev);
            newRange.collapse(false);
            sel.removeAllRanges();
            sel.addRange(newRange);
          } else if (root) {
            const lineAbove = document.createElement("div");
            lineAbove.appendChild(document.createElement("br"));
            root.insertBefore(lineAbove, pre);
            const newRange = document.createRange();
            newRange.setStart(lineAbove, 0);
            newRange.collapse(true);
            sel.removeAllRanges();
            sel.addRange(newRange);
            emitChangeFromDom();
          }
          return;
        }
      }
    }

    if (e.key === "Backspace") {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const pre = findClosestTag(range.commonAncestorContainer, "pre");
        if (pre && range.collapsed) {
          const preText = pre.textContent || "";
          if (preText.trim() === "" || preText === "\n") {
            e.preventDefault();
            const parent = pre.parentNode;
            if (parent) {
              const replacement = document.createElement("div");
              replacement.appendChild(document.createElement("br"));
              parent.replaceChild(replacement, pre);
              const newRange = document.createRange();
              newRange.setStart(replacement, 0);
              newRange.collapse(true);
              sel.removeAllRanges();
              sel.addRange(newRange);
              emitChangeFromDom();
            }
            return;
          }
        }
      }
    }
  };

  const isEmpty = !value || !value.trim();

  return (
    <div className="w-full flex flex-col">
      {/* Barra de formatação estilo Telegram */}
      <div
        role="toolbar"
        aria-label="Formatação da mensagem"
        className="flex flex-wrap items-center gap-0.5 pb-1.5 mb-1.5 border-b border-gray-700/60"
      >
        <button
          type="button"
          onClick={() => applyWrapTag("b")}
          className={getToolbarButtonClass(activeStyles.bold)}
          aria-pressed={activeStyles.bold ? "true" : "false"}
          title="Negrito (Ctrl+B)"
          aria-label="Negrito"
        >
          <Bold className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => applyWrapTag("i")}
          className={getToolbarButtonClass(activeStyles.italic)}
          aria-pressed={activeStyles.italic ? "true" : "false"}
          title="Itálico (Ctrl+I)"
          aria-label="Itálico"
        >
          <Italic className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => applyWrapTag("u")}
          className={getToolbarButtonClass(activeStyles.underline)}
          aria-pressed={activeStyles.underline ? "true" : "false"}
          title="Sublinhado (Ctrl+U)"
          aria-label="Sublinhado"
        >
          <Underline className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => applyWrapTag("s")}
          className={getToolbarButtonClass(activeStyles.strike)}
          aria-pressed={activeStyles.strike ? "true" : "false"}
          title="Riscado"
          aria-label="Riscado"
        >
          <Strikethrough className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() =>
            applyWrapTag("code", {
              class: "font-mono bg-[#17212b] px-1 rounded text-[#90caf9]",
            })
          }
          className={getToolbarButtonClass(activeStyles.code)}
          aria-pressed={activeStyles.code ? "true" : "false"}
          title="Código inline"
          aria-label="Código inline"
        >
          <Code className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() =>
            applyWrapTag("pre", {
              class:
                "font-mono bg-[#17212b] p-1.5 rounded text-xs text-[#90caf9] my-0.5",
            })
          }
          className={getToolbarButtonClass(activeStyles.pre)}
          aria-pressed={activeStyles.pre ? "true" : "false"}
          title="Bloco de código"
          aria-label="Bloco de código"
        >
          <FileCode className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() =>
            applyWrapTag("blockquote", {
              class:
                "border-l-2 border-[#5288c1] pl-2 my-0.5 italic text-gray-200",
            })
          }
          className={getToolbarButtonClass(activeStyles.blockquote)}
          aria-pressed={activeStyles.blockquote ? "true" : "false"}
          title="Citação"
          aria-label="Citação"
        >
          <Quote className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() =>
            applyWrapTag("span", {
              "data-tg-spoiler": "true",
              class:
                "bg-gray-600/50 border border-dashed border-gray-400/60 rounded px-1",
            })
          }
          className={getToolbarButtonClass(activeStyles.spoiler)}
          aria-pressed={activeStyles.spoiler ? "true" : "false"}
          title="Spoiler"
          aria-label="Spoiler"
        >
          <EyeOff className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={openLinkModalFromSelection}
          className={getToolbarButtonClass(activeStyles.link)}
          aria-pressed={activeStyles.link ? "true" : "false"}
          title="Inserir ou editar link no texto"
          aria-label="Inserir ou editar link no texto"
        >
          <Link2 className="w-3.5 h-3.5" />
        </button>
        <div className="h-3.5 w-px bg-gray-700/60 mx-1" aria-hidden="true" />
        <button
          type="button"
          onClick={handleClearFormatting}
          className="p-1 rounded hover:bg-[#17212b] text-gray-300 hover:text-rose-400 transition border border-transparent"
          title="Limpar formatação"
          aria-label="Limpar formatação"
        >
          <RemoveFormatting className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Campo editável formatado (sem mostrar tags HTML cruas) */}
      <div className="relative w-full">
        {isEmpty && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 text-sm text-gray-400 select-none"
          >
            {placeholder}
          </span>
        )}
        <div
          id={id}
          ref={editorRef}
          role="textbox"
          aria-multiline="true"
          aria-label={ariaLabel}
          contentEditable
          suppressContentEditableWarning
          // Mantém o atributo placeholder para seletores getByPlaceholder existentes
          {...({ placeholder } as React.HTMLAttributes<HTMLDivElement>)}
          onInput={emitChangeFromDom}
          onClick={(e) => {
            handleEditorClick(e);
            updateActiveStyles();
          }}
          onKeyUp={updateActiveStyles}
          onMouseUp={updateActiveStyles}
          onFocus={updateActiveStyles}
          onKeyDown={handleKeyDown}
          style={{ minHeight: `${minRows * 1.5}rem` }}
          className="w-full bg-transparent outline-none text-sm text-gray-100 whitespace-pre-wrap break-words leading-relaxed"
        />
      </div>

      {/* Modal de Link de Texto (usado tanto no compositor quanto no Editar) */}
      {showLinkModal && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-[60] p-4"
          onClick={(e) => e.stopPropagation()}
        >
          <div
            role="dialog"
            aria-label="Inserir Link em Palavra do Texto"
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-sm w-full p-5 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
              <Link2 className="w-4 h-4 text-[#5288c1]" />{" "}
              {isEditingExistingLink
                ? "Editar Link do Texto"
                : "Inserir Link em Palavra do Texto"}
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Insere um hyperlink direto em uma palavra ou frase no corpo da
              mensagem.
            </p>
            {linkError && (
              <div
                role="alert"
                className="mb-3 px-3 py-2 rounded-lg bg-red-900/50 border border-red-700 text-xs text-red-200"
              >
                {linkError}
              </div>
            )}
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="field-text-link-word"
                  className="text-xs text-gray-400 block mb-1"
                >
                  Palavra / Texto exibido
                </label>
                <input
                  id="field-text-link-word"
                  type="text"
                  placeholder="Ex: CLIQUE AQUI!"
                  value={linkWord}
                  onChange={(e) => {
                    setLinkWord(e.target.value);
                    setLinkError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleConfirmLinkModal();
                    }
                  }}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                  autoFocus
                />
              </div>
              <div>
                <label
                  htmlFor="field-text-link-url"
                  className="text-xs text-gray-400 block mb-1"
                >
                  URL de destino
                </label>
                <input
                  id="field-text-link-url"
                  type="text"
                  placeholder="https://seulink.com"
                  value={linkUrl}
                  onChange={(e) => {
                    setLinkUrl(e.target.value);
                    setLinkError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleConfirmLinkModal();
                    }
                  }}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
            </div>
            <div className="mt-5 flex items-center justify-between gap-2 pt-2 border-t border-gray-800">
              {isEditingExistingLink ? (
                <button
                  type="button"
                  onClick={handleRemoveLink}
                  className="px-2.5 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-900/20 transition rounded-lg flex items-center gap-1"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Remover Link
                </button>
              ) : (
                <span />
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowLinkModal(false)}
                  className="px-3 py-1.5 text-xs text-gray-400 hover:text-white transition rounded-lg"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmLinkModal}
                  className="px-4 py-1.5 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium transition shadow"
                >
                  {isEditingExistingLink ? "Salvar Link" : "Inserir Link"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
