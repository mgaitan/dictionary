(function () {
  const glossLines = Array.from(document.querySelectorAll(".gloss-line"));
  if (glossLines.length === 0) {
    return;
  }

  const dictionaryId = glossLines[0].dataset.dictionaryId || "de-es";
  const tokenPattern = /\p{L}[\p{L}\p{M}·'’-]*/gu;
  const uniqueTerms = new Map();

  function normalizeToken(token) {
    return token
      .trim()
      .replaceAll("ß", "ss")
      .replaceAll("ẞ", "ss")
      .replaceAll("·", "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function collectTerms(text) {
    const matches = text.match(tokenPattern) || [];
    for (const match of matches) {
      const trimmed = match.trim();
      if (trimmed.length < 2) {
        continue;
      }
      const normalized = normalizeToken(trimmed);
      if (!normalized) {
        continue;
      }
      uniqueTerms.set(normalized, trimmed);
    }
  }

  glossLines.forEach((line) => {
    collectTerms(line.textContent || "");
  });

  const terms = Array.from(uniqueTerms.values());
  if (terms.length === 0) {
    return;
  }

  function walkTextNodes(root, callback) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        if (node.parentElement?.closest("a")) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    const nodes = [];
    let current = walker.nextNode();
    while (current) {
      nodes.push(current);
      current = walker.nextNode();
    }

    nodes.forEach(callback);
  }

  function linkifyNode(node, linkMap) {
    const text = node.nodeValue;
    if (!text) {
      return;
    }

    tokenPattern.lastIndex = 0;
    let lastIndex = 0;
    let match = tokenPattern.exec(text);
    if (!match) {
      return;
    }

    const fragment = document.createDocumentFragment();
    do {
      const [token] = match;
      const start = match.index;
      const end = start + token.length;

      if (start > lastIndex) {
        fragment.append(text.slice(lastIndex, start));
      }

      const normalized = normalizeToken(token);
      const linked = linkMap.get(normalized);
      if (linked) {
        const anchor = document.createElement("a");
        anchor.className = "gloss-link";
        anchor.href = linked.url;
        anchor.textContent = token;
        anchor.title = `Buscar ${linked.headword}`;
        fragment.append(anchor);
      } else {
        fragment.append(token);
      }

      lastIndex = end;
      match = tokenPattern.exec(text);
    } while (match);

    if (lastIndex < text.length) {
      fragment.append(text.slice(lastIndex));
    }

    node.parentNode?.replaceChild(fragment, node);
  }

  fetch(`/api/linkable-terms?dict=${encodeURIComponent(dictionaryId)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(terms),
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error("lookup_failed");
      }
      return response.json();
    })
    .then((payload) => {
      const results = payload.results || {};
      const linkMap = new Map();
      for (const [normalized, value] of Object.entries(results)) {
        if (!value || !value.url) {
          continue;
        }
        linkMap.set(normalized, value);
      }

      if (linkMap.size === 0) {
        return;
      }

      glossLines.forEach((line) => {
        walkTextNodes(line, (node) => linkifyNode(node, linkMap));
      });
    })
    .catch(() => {});
})();
