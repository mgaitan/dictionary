(function () {
  const searchInput = document.getElementById("search-input");
  if (!searchInput) {
    return;
  }

  const dictInput = document.querySelector('input[name="dict"]');
  const getDictId = () => (dictInput ? dictInput.value : "de-es");

  // Inject dropdown list into the .search-box wrapper (positioned relative).
  const searchBox = searchInput.closest(".search-box");
  if (!searchBox) {
    return;
  }

  const dropdown = document.createElement("ul");
  dropdown.id = "autocomplete-list";
  dropdown.className = "autocomplete-list";
  dropdown.setAttribute("role", "listbox");
  dropdown.hidden = true;
  searchBox.appendChild(dropdown);

  // Wire up ARIA attributes on the input.
  searchInput.setAttribute("role", "combobox");
  searchInput.setAttribute("aria-autocomplete", "list");
  searchInput.setAttribute("aria-controls", "autocomplete-list");
  searchInput.setAttribute("aria-expanded", "false");

  let debounceTimer = null;
  let currentSuggestions = [];
  let activeIndex = -1;

  function clearDropdown() {
    dropdown.hidden = true;
    dropdown.innerHTML = "";
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.removeAttribute("aria-activedescendant");
    activeIndex = -1;
    currentSuggestions = [];
  }

  function selectSuggestion(headword) {
    searchInput.value = headword;
    clearDropdown();
    searchInput.form.submit();
  }

  function setActiveItem(index) {
    const items = dropdown.querySelectorAll(".autocomplete-option");
    items.forEach((item, i) => {
      const active = i === index;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    const activeItem = items[index];
    if (activeItem) {
      searchInput.setAttribute("aria-activedescendant", activeItem.id);
      activeItem.scrollIntoView({ block: "nearest" });
    } else {
      searchInput.removeAttribute("aria-activedescendant");
    }
  }

  function renderSuggestions(suggestions) {
    dropdown.innerHTML = "";
    if (suggestions.length === 0) {
      dropdown.hidden = true;
      searchInput.setAttribute("aria-expanded", "false");
      currentSuggestions = [];
      activeIndex = -1;
      return;
    }
    currentSuggestions = suggestions;
    activeIndex = -1;
    suggestions.forEach((headword, i) => {
      const li = document.createElement("li");
      li.id = `autocomplete-option-${i}`;
      li.className = "autocomplete-option";
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.textContent = headword;
      // Use mousedown so the event fires before the input's blur.
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectSuggestion(headword);
      });
      dropdown.appendChild(li);
    });
    dropdown.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }

  function fetchSuggestions(value) {
    const q = value.trim();
    if (!q) {
      clearDropdown();
      return;
    }
    fetch(
      `/api/autocomplete?dict=${encodeURIComponent(getDictId())}&q=${encodeURIComponent(q)}`,
    )
      .then((response) => {
        if (!response.ok) {
          console.warn(`autocomplete lookup failed: ${response.status}`);
          return { suggestions: [] };
        }
        return response.json();
      })
      .then((data) => {
        renderSuggestions(data.suggestions || []);
      })
      .catch(() => {
        clearDropdown();
      });
  }

  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      fetchSuggestions(searchInput.value);
    }, 200);
  });

  searchInput.addEventListener("keydown", (e) => {
    if (dropdown.hidden) {
      return;
    }
    const count = currentSuggestions.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % count;
      setActiveItem(activeIndex);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + count) % count;
      setActiveItem(activeIndex);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectSuggestion(currentSuggestions[activeIndex]);
    } else if (e.key === "Escape") {
      clearDropdown();
    }
  });

  // Close the dropdown when the input loses focus, but allow a brief window
  // so that a mousedown on a suggestion option fires first.
  searchInput.addEventListener("blur", () => {
    setTimeout(() => {
      clearDropdown();
    }, 150);
  });
})();
