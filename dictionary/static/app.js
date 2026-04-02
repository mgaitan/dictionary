(function () {
  const glossLines = Array.from(document.querySelectorAll(".gloss-line"));
  if (glossLines.length === 0) {
    return;
  }

  const dictionaryId = glossLines[0].dataset.dictionaryId || "de-es";
  const sameDictionaryId = glossLines[0].dataset.sameDictionaryId || "";
  const tokenPattern = /\p{L}[\p{L}\p{M}·''-]*/gu;
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

  function linkifyNode(node, inverseLinkMap, sameLinkMap) {
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
      const inverseLinked = inverseLinkMap.get(normalized);
      const sameLinked = sameLinkMap.get(normalized);
      if (inverseLinked) {
        const anchor = document.createElement("a");
        anchor.className = "gloss-link";
        anchor.href = inverseLinked.url;
        anchor.textContent = token;
        anchor.title = `Buscar ${inverseLinked.headword}`;
        fragment.append(anchor);
      } else if (sameLinked) {
        const anchor = document.createElement("a");
        anchor.className = "gloss-link gloss-link-same";
        anchor.href = sameLinked.url;
        anchor.textContent = token;
        anchor.title = `Buscar ${sameLinked.headword}`;
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

  function fetchLinkableTerms(dictId) {
    return fetch(`/api/linkable-terms?dict=${encodeURIComponent(dictId)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(terms),
    }).then((response) => {
      if (!response.ok) {
        console.warn(`linkable-terms lookup failed for dict=${dictId}: ${response.status}`);
        return { results: {} };
      }
      return response.json();
    });
  }

  const requests = [fetchLinkableTerms(dictionaryId)];
  if (sameDictionaryId && sameDictionaryId !== dictionaryId) {
    requests.push(fetchLinkableTerms(sameDictionaryId));
  } else {
    requests.push(Promise.resolve({ results: {} }));
  }

  Promise.all(requests)
    .then(([inversePayload, samePayload]) => {
      const inverseLinkMap = new Map();
      for (const [normalized, value] of Object.entries(
        inversePayload.results || {},
      )) {
        if (!value || !value.url) {
          continue;
        }
        inverseLinkMap.set(normalized, value);
      }

      const sameLinkMap = new Map();
      for (const [normalized, value] of Object.entries(
        samePayload.results || {},
      )) {
        // Inverse links take priority: skip same-language matches that are
        // already covered by a cross-dictionary link.
        if (!value || !value.url || inverseLinkMap.has(normalized)) {
          continue;
        }
        sameLinkMap.set(normalized, value);
      }

      if (inverseLinkMap.size === 0 && sameLinkMap.size === 0) {
        return;
      }

      glossLines.forEach((line) => {
        walkTextNodes(line, (node) =>
          linkifyNode(node, inverseLinkMap, sameLinkMap),
        );
      });
    })
    .catch(() => {});
})();
