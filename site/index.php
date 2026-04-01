<?php
declare(strict_types=1);

$databasePath = __DIR__ . '/data/dictionary.sqlite';
$query = trim((string) ($_GET['q'] ?? ''));
$normalizedQuery = normalize_for_search($query);
$page = max(1, (int) ($_GET['page'] ?? 1));
$limit = 25;
$error = null;
$results = [];
$totalResults = 0;
$totalPages = 0;
$stats = [
    'entries' => 0,
    'senses' => 0,
];

if (!is_file($databasePath)) {
    $error = "No encuentro la base SQLite en {$databasePath}. Ejecutá el importador en Python antes de abrir el sitio.";
} else {
    try {
        $db = new PDO('sqlite:' . $databasePath);
        $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $stats = load_stats($db);

        if ($normalizedQuery !== '') {
            $search = search_entries($db, $query, $normalizedQuery, $limit, $page);
            $totalResults = $search['total'];
            $totalPages = max(1, (int) ceil($totalResults / $limit));
            $page = min($page, $totalPages);
            if ($search['page'] !== $page) {
                $search = search_entries($db, $query, $normalizedQuery, $limit, $page);
            }
            $results = $search['entries'];
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

function normalize_for_search(string $value): string
{
    $trimmed = trim($value);
    if ($trimmed === '') {
        return '';
    }

    $folded = strtr($trimmed, [
        'Ä' => 'Ae',
        'Ö' => 'Oe',
        'Ü' => 'Ue',
        'ä' => 'ae',
        'ö' => 'oe',
        'ü' => 'ue',
        'ß' => 'ss',
        'Æ' => 'AE',
        'æ' => 'ae',
        'Œ' => 'OE',
        'œ' => 'oe',
        'Ø' => 'O',
        'ø' => 'o',
        'Å' => 'A',
        'å' => 'a',
        'Ñ' => 'N',
        'ñ' => 'n',
        'Ç' => 'C',
        'ç' => 'c',
        '·' => '',
    ]);

    $ascii = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $folded);
    if ($ascii === false) {
        $ascii = $folded;
    }

    $ascii = strtolower($ascii);
    $ascii = preg_replace('/[^a-z0-9]+/', ' ', $ascii) ?? '';
    return trim(preg_replace('/\s+/', ' ', $ascii) ?? '');
}

function load_stats(PDO $db): array
{
    $entryCount = (int) $db->query('SELECT COUNT(*) FROM entries')->fetchColumn();
    $senseCount = (int) $db->query('SELECT COUNT(*) FROM senses')->fetchColumn();

    return [
        'entries' => $entryCount,
        'senses' => $senseCount,
    ];
}

function search_entries(PDO $db, string $query, string $normalizedQuery, int $limit, int $page): array
{
    $prefix = $normalizedQuery . '%';
    $contains = '%' . $normalizedQuery . '%';
    $offset = max(0, ($page - 1) * $limit);

    $countStatement = $db->prepare(
        <<<SQL
        SELECT COUNT(DISTINCT e.id)
        FROM search_terms st
        INNER JOIN entries e ON e.id = st.entry_id
        WHERE st.normalized_term LIKE :contains
        SQL
    );
    $countStatement->bindValue(':contains', $contains, PDO::PARAM_STR);
    $countStatement->execute();
    $total = (int) $countStatement->fetchColumn();

    if ($total === 0) {
        return [
            'total' => 0,
            'page' => 1,
            'entries' => [],
        ];
    }

    $statement = $db->prepare(
        <<<SQL
        SELECT
            e.id,
            e.headword,
            e.decoded_complete,
            CASE
                WHEN e.headword = :raw_query THEN -1
                ELSE 0
            END AS exact_headword_rank,
            MIN(
                CASE
                    WHEN st.normalized_term = :exact_normalized THEN 0
                    WHEN st.normalized_term LIKE :prefix THEN 1
                    ELSE 2
                END
            ) AS rank,
            MIN(LENGTH(st.normalized_term)) AS term_length
        FROM search_terms st
        INNER JOIN entries e ON e.id = st.entry_id
        WHERE st.normalized_term LIKE :contains
        GROUP BY e.id, e.headword, e.decoded_complete
        ORDER BY exact_headword_rank ASC, rank ASC, term_length ASC, e.normalized_headword ASC
        LIMIT :limit
        OFFSET :offset
        SQL
    );
    $statement->bindValue(':raw_query', $query, PDO::PARAM_STR);
    $statement->bindValue(':exact_normalized', $normalizedQuery, PDO::PARAM_STR);
    $statement->bindValue(':prefix', $prefix, PDO::PARAM_STR);
    $statement->bindValue(':contains', $contains, PDO::PARAM_STR);
    $statement->bindValue(':limit', $limit, PDO::PARAM_INT);
    $statement->bindValue(':offset', $offset, PDO::PARAM_INT);
    $statement->execute();
    $entries = $statement->fetchAll(PDO::FETCH_ASSOC);

    if (!$entries) {
        return [
            'total' => $total,
            'page' => $page,
            'entries' => [],
        ];
    }

    $entryIds = array_map(static fn(array $entry): int => (int) $entry['id'], $entries);
    $placeholders = implode(',', array_fill(0, count($entryIds), '?'));
    $senseStatement = $db->prepare(
        "SELECT entry_id, sense_index, source, glosses_json, tags_json
         FROM senses
         WHERE entry_id IN ($placeholders)
         ORDER BY entry_id ASC, sense_index ASC"
    );
    foreach ($entryIds as $index => $entryId) {
        $senseStatement->bindValue($index + 1, $entryId, PDO::PARAM_INT);
    }
    $senseStatement->execute();

    $sensesByEntry = [];
    foreach ($senseStatement->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $sensesByEntry[(int) $row['entry_id']][] = [
            'source' => (string) $row['source'],
            'glosses' => decode_json_list((string) $row['glosses_json']),
            'tags' => decode_json_list((string) $row['tags_json']),
        ];
    }

    foreach ($entries as &$entry) {
        $entry['decoded_complete'] = (bool) $entry['decoded_complete'];
        $entry['senses'] = $sensesByEntry[(int) $entry['id']] ?? [];
    }
    unset($entry);

    return [
        'total' => $total,
        'page' => $page,
        'entries' => $entries,
    ];
}

function decode_json_list(string $value): array
{
    $decoded = json_decode($value, true);
    if (!is_array($decoded)) {
        return [];
    }

    return array_values(
        array_filter(
            array_map(static fn($item): string => trim((string) $item), $decoded),
            static fn(string $item): bool => $item !== ''
        )
    );
}

function build_page_url(string $query, int $page): string
{
    return './index.php?' . http_build_query([
        'q' => $query,
        'page' => $page,
    ]);
}

function build_page_window(int $page, int $totalPages, int $radius = 2): array
{
    $start = max(1, $page - $radius);
    $end = min($totalPages, $page + $radius);
    return range($start, $end);
}

function render_gloss_html(string $gloss): string
{
    $pattern = '~(\[[^\]]+\]|<[^>]+>|(?:^|\s)[a-z]\)|(?<![\pL])(?:m|f|n|pl|mpl|fpl|adj|adv|vt|vi|vr|vtr|pron|prep|conj|interj|num|sg|subst|tr|intr)(?![\pL]))~u';
    $parts = preg_split($pattern, $gloss, -1, PREG_SPLIT_DELIM_CAPTURE | PREG_SPLIT_NO_EMPTY);
    if (!is_array($parts) || $parts === []) {
        return htmlspecialchars($gloss, ENT_QUOTES, 'UTF-8');
    }

    $html = '';
    foreach ($parts as $part) {
        if ($part === '') {
            continue;
        }

        $escaped = htmlspecialchars($part, ENT_QUOTES, 'UTF-8');
        if (preg_match('/^\[[^\]]+\]$/u', $part) === 1) {
            $html .= '<span class="gloss-note">' . $escaped . '</span>';
        } elseif (preg_match('/^<[^>]+>$/u', $part) === 1) {
            $html .= '<span class="gloss-label">' . $escaped . '</span>';
        } elseif (preg_match('/^\s*[a-z]\)$/u', $part) === 1) {
            $html .= '<span class="gloss-marker">' . $escaped . '</span>';
        } elseif (preg_match('/^(m|f|n|pl|mpl|fpl|adj|adv|vt|vi|vr|vtr|pron|prep|conj|interj|num|sg|subst|tr|intr)$/u', trim($part)) === 1) {
            $html .= '<span class="gloss-grammar">' . $escaped . '</span>';
        } else {
            $html .= $escaped;
        }
    }

    return $html;
}
?>
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>UniLex Deutsch-Espanol</title>
    <meta
      name="description"
      content="Buscador PHP + SQLite para el diccionario aleman-espanol extraido desde UniLex."
    >
    <link rel="stylesheet" href="./styles.css">
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <p class="eyebrow">UniLex reconstruido</p>
        <h1>Diccionario alemán-español</h1>
        <p class="lede">
          Búsqueda server-side en PHP sobre una base SQLite generada con scripts en Python.
          No hace falta descargar el diccionario entero en el navegador.
        </p>
      </section>

      <section class="panel controls" aria-label="Controles de búsqueda">
        <form class="search-form" method="get" action="./index.php">
          <div class="search-box">
            <label for="search-input">Palabra fuente</label>
            <input
              id="search-input"
              name="q"
              type="search"
              placeholder="Ej. Tabakqualm, Macher, verabschieden"
              autocomplete="off"
              spellcheck="false"
              value="<?= htmlspecialchars($query, ENT_QUOTES, 'UTF-8') ?>"
            >
          </div>

          <div class="actions">
            <button type="submit">Buscar</button>
            <a class="file-button" href="./index.php">Limpiar</a>
          </div>
        </form>

        <p class="status" role="status" aria-live="polite">
          <?php if ($error !== null): ?>
            <?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?>
          <?php elseif ($normalizedQuery === ''): ?>
            <?= number_format($stats['entries']) ?> entradas y <?= number_format($stats['senses']) ?> acepciones listas para consultar.
          <?php else: ?>
            <?= number_format($totalResults) ?> resultado<?= $totalResults === 1 ? '' : 's' ?> para “<?= htmlspecialchars($query, ENT_QUOTES, 'UTF-8') ?>”.
          <?php endif; ?>
        </p>
      </section>

      <section class="panel results-panel" aria-label="Resultados">
        <div class="results-meta">
          <p id="result-count">
            <?php if ($normalizedQuery === ''): ?>
              Escribí una palabra para empezar
            <?php else: ?>
              Página <?= $page ?> de <?= max(1, $totalPages) ?>
            <?php endif; ?>
          </p>
          <p class="hint">
            Prioriza coincidencia exacta, luego prefijo y después contenido.
          </p>
        </div>

        <div class="results">
          <?php if ($error !== null): ?>
            <div class="empty-state">La aplicación no pudo abrir la base de datos.</div>
          <?php elseif ($normalizedQuery === ''): ?>
            <div class="empty-state">
              Probá con <code>Macher</code>, <code>Machbarkeit</code>,
              <code>Tabakqualm</code> o <code>Verabschiedung</code>.
            </div>
          <?php elseif (!$results): ?>
            <div class="empty-state">No encontré coincidencias para “<?= htmlspecialchars($query, ENT_QUOTES, 'UTF-8') ?>”.</div>
          <?php else: ?>
            <?php foreach ($results as $entry): ?>
              <article class="entry-card">
                <header class="entry-header">
                  <div>
                    <h2 class="entry-title"><?= htmlspecialchars((string) $entry['headword'], ENT_QUOTES, 'UTF-8') ?></h2>
                    <p class="entry-subtitle">
                      <?= $entry['decoded_complete'] ? 'Entrada decodificada completamente' : 'Entrada parcialmente reconstruida' ?>
                    </p>
                  </div>
                </header>

                <ol class="sense-list">
                  <?php foreach ($entry['senses'] as $sense): ?>
                    <li class="sense-item">
                      <?php if ($sense['tags']): ?>
                        <div class="sense-tags">
                          <?php foreach ($sense['tags'] as $tag): ?>
                            <span class="tag"><?= htmlspecialchars($tag, ENT_QUOTES, 'UTF-8') ?></span>
                          <?php endforeach; ?>
                        </div>
                      <?php endif; ?>

                      <?php if ($sense['source'] !== ''): ?>
                        <p class="sense-source"><?= htmlspecialchars($sense['source'], ENT_QUOTES, 'UTF-8') ?></p>
                      <?php endif; ?>

                      <ul class="sense-glosses">
                        <?php foreach ($sense['glosses'] as $gloss): ?>
                          <li><?= render_gloss_html($gloss) ?></li>
                        <?php endforeach; ?>
                      </ul>
                    </li>
                  <?php endforeach; ?>
                </ol>
              </article>
            <?php endforeach; ?>

            <?php if ($totalPages > 1): ?>
              <nav class="pagination" aria-label="Paginación de resultados">
                <?php if ($page > 1): ?>
                  <a class="page-link" href="<?= htmlspecialchars(build_page_url($query, $page - 1), ENT_QUOTES, 'UTF-8') ?>">Anterior</a>
                <?php endif; ?>

                <?php foreach (build_page_window($page, $totalPages) as $pageNumber): ?>
                  <?php if ($pageNumber === $page): ?>
                    <span class="page-link current"><?= $pageNumber ?></span>
                  <?php else: ?>
                    <a class="page-link" href="<?= htmlspecialchars(build_page_url($query, $pageNumber), ENT_QUOTES, 'UTF-8') ?>"><?= $pageNumber ?></a>
                  <?php endif; ?>
                <?php endforeach; ?>

                <?php if ($page < $totalPages): ?>
                  <a class="page-link" href="<?= htmlspecialchars(build_page_url($query, $page + 1), ENT_QUOTES, 'UTF-8') ?>">Siguiente</a>
                <?php endif; ?>
              </nav>
            <?php endif; ?>
          <?php endif; ?>
        </div>
      </section>
    </main>
  </body>
</html>
