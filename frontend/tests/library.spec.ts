import { test, expect } from '@playwright/test';
import path from 'node:path';

test('import, search, edit, download, reload and back up a book', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  const originalTitle =
    testInfo.project.name === 'phone' ? 'The Quiet Library — phone' : 'The Quiet Library';
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve(`../samples/${originalTitle}.epub`));
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('Quiet');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${originalTitle}`, exact: true }).click();
  await expect(page.getByRole('heading', { name: originalTitle, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit details' }).click();
  const title = `A Quiet Library — ${testInfo.project.name}`;
  await page.getByLabel('Title', { exact: true }).fill(title);
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download EPUB' }).click();
  expect((await downloadPromise).suggestedFilename()).toBe(`${originalTitle}.epub`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('book-detail.png'), fullPage: true });
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const backupPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download backup' }).click();
  expect((await backupPromise).suggestedFilename()).toBe('stacks.backup.zip');
  await page.getByRole('button', { name: /Sign out/ }).click();
  await expect(page.getByLabel('Library password')).toBeVisible();
});

test('catalog layout works with multiple books and a missing search result', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(
      [
        'A Field Guide to Rain',
        'Notes from the Coast',
        'An Ordinary Afternoon',
        'The Long Way Home',
        'Small Hours',
      ].map((name) => path.resolve(`../samples/${name}.epub`)),
    );
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('Alex Reed');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open Small Hours', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('library.png'), fullPage: true });
  await page.getByLabel('Search books or authors').fill('there-is-no-such-book');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No books found.' })).toBeVisible();
});

test('catalog page survives detail, back, reload, and unsubmitted search text', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(
      Array.from({ length: 26 }, (_, i) =>
        path.resolve(`../samples/Page Test ${String(i).padStart(2, '0')}.epub`),
      ),
    );
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('Page Test');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/q=Page/);
  await page.getByLabel('Search books or authors').fill('unsubmitted');
  await page.getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(page).toHaveURL(/offset=24/);
  await expect(page.getByLabel('Search books or authors')).toHaveValue('Page Test');
  const book = page.getByRole('button', { name: /^Open Page Test/ }).first();
  const name = await book.getAttribute('aria-label');
  await book.click();
  await expect(page).toHaveURL(/book=/);
  await page.goBack();
  await expect(page.getByRole('button', { name: name!, exact: true })).toBeVisible();
  await expect(page).toHaveURL(/offset=24/);
  await page.reload();
  await expect(page.getByRole('button', { name: name!, exact: true })).toBeVisible();
  await expect(page).toHaveURL(/offset=24/);
});

test('PDF details and distinct series survive reload', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve('../samples/An Open Page.pdf'));
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('An Open Page');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Open An Open Page', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await page.getByRole('button', { name: 'Organize editions & series' }).click();
  await page.getByLabel('Language', { exact: true }).fill('sl');
  await page.getByText('Create a separate series', { exact: true }).click();
  await page.getByLabel('Series name', { exact: true }).fill('Reading Rooms');
  await page.getByLabel('Run label').fill(testInfo.project.name);
  await page.getByRole('button', { name: 'Create series', exact: true }).click();
  await expect(
    page.getByRole('group', { name: `Reading Rooms · ${testInfo.project.name}`, exact: true }),
  ).toBeVisible();
  await page.getByLabel('Find a series').fill('no-matching-series');
  await page.getByRole('button', { name: 'Search series', exact: true }).click();
  await expect(page.getByLabel('Existing series').locator('option')).toHaveCount(1);
  await page
    .getByRole('group', { name: `Reading Rooms · ${testInfo.project.name}`, exact: true })
    .getByLabel('Issue or volume label')
    .fill('Annual 2024');
  await page.getByLabel('Reading order').last().fill('2.5');
  await page.getByRole('button', { name: 'Save editions & series', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Organize editions & series' })).toBeVisible();
  await page.reload();
  await expect(
    page.getByText(new RegExp(`Reading Rooms · ${testInfo.project.name} · Annual 2024`)),
  ).toBeVisible();
  await expect(page.getByText('EBOOK · sl', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Organize editions & series' }).click();
  await page
    .getByRole('group', { name: `Reading Rooms · ${testInfo.project.name}`, exact: true })
    .getByRole('button', { name: 'Edit this series' })
    .click();
  await page
    .getByLabel('Series run label', { exact: true })
    .fill(`${testInfo.project.name} · corrected`);
  const workId = new URL(page.url()).searchParams.get('book');
  const current = await (await page.request.get(`/api/works/${workId}`)).json();
  const concurrent = await page.request.patch(`/api/works/${workId}`, {
    headers: { 'X-Stacks-Request': '1' },
    data: {
      revision: current.revision,
      title: current.title,
      authors: current.authors,
      description: current.description,
      editions: current.editions.map(
        (e: { id: string; language: string; publisher: string; identifier: string }) => ({
          id: e.id,
          language: 'de',
          publisher: e.publisher,
          identifier: e.identifier,
        }),
      ),
    },
  });
  expect(concurrent.ok()).toBe(true);
  await page.getByRole('button', { name: 'Save series metadata', exact: true }).click();
  await expect(
    page.getByRole('group', {
      name: `Reading Rooms · ${testInfo.project.name} · corrected`,
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Save editions & series', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('another tab');
  await page.reload();
  await expect(page.getByText('EBOOK · de', { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      new RegExp(`Reading Rooms · ${testInfo.project.name} · corrected · Annual 2024`),
    ),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('editions-series.png'), fullPage: true });
});

test('group alternate formats, split, undo, and preserve separate narrations', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(
      ['Ways to Read.epub', 'A Different Format.pdf'].map((n) => path.resolve(`../samples/${n}`)),
    );
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('A Different Format');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Open A Different Format', exact: true }).click();
  const originalLink = await page.getByRole('link', { name: 'Download PDF' }).getAttribute('href');
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByRole('combobox', { name: 'Action', exact: true }).selectOption('representation');
  await page
    .getByLabel('Format to move')
    .selectOption({ label: 'PDF · Unknown language · A Different Format.pdf' });
  await page.getByLabel('Find the target book').fill('Ways to Read');
  await page.getByRole('button', { name: 'Find target', exact: true }).click();
  await page.getByRole('button', { name: /Ways to Read.*EPUB/ }).click();
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await expect(page.getByRole('region', { name: 'Grouping preview' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('group-preview.png'), fullPage: true });
  for (const choice of await page
    .getByRole('region', { name: 'Grouping preview' })
    .locator('select')
    .all())
    await choice.selectOption('target');
  await page.getByRole('button', { name: 'Confirm grouping', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toHaveAttribute(
    'href',
    originalLink!,
  );
  await expect(page.getByRole('link', { name: 'Download EPUB' })).toBeVisible();
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByRole('combobox', { name: 'Action', exact: true }).selectOption('split');
  await page
    .getByLabel('Format to move')
    .selectOption({ label: 'PDF · en · A Different Format.pdf' });
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await page.getByRole('button', { name: 'Confirm split', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toHaveAttribute(
    'href',
    originalLink!,
  );
  await expect(page.getByRole('link', { name: 'Download EPUB' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByRole('button', { name: 'Undo grouping or split' }).click();
  await expect(page.getByRole('link', { name: 'Download EPUB' })).toBeVisible();
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByRole('button', { name: 'Undo grouping or split' }).click();
  await expect(
    page.getByRole('heading', { name: 'A Different Format', exact: true }),
  ).toBeVisible();

  await page.getByRole('button', { name: '← Back to library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(
      ['tone.mp3', 'tone.m4a'].map((n) => path.resolve(`../backend/tests/fixtures/${n}`)),
    );
  await expect(page.getByRole('status')).toContainText(/added/);
  const catalog = await (await page.request.get('/api/catalog?q=A%20Listening%20Room')).json();
  for (const work of catalog.items) {
    const edition = work.editions[0];
    const narrator = edition.representations[0].format === 'mp3' ? 'Reader One' : 'Reader Two';
    const response = await page.request.patch(`/api/works/${work.id}`, {
      headers: { 'X-Stacks-Request': '1' },
      data: {
        revision: work.revision,
        title: work.title,
        authors: work.authors,
        description: work.description,
        editions: [{ id: edition.id, language: 'en', publisher: '', identifier: '', narrator }],
      },
    });
    expect(response.ok()).toBe(true);
  }
  const source = catalog.items.find(
    (w: { editions: { representations: { format: string }[] }[] }) =>
      w.editions[0].representations[0].format === 'mp3',
  );
  await page.goto(`/?book=${source.id}`);
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByLabel('Find the target book').fill('A Listening Room');
  await page.getByRole('button', { name: 'Find target', exact: true }).click();
  await page.getByRole('button', { name: /A Listening Room.*Reader Two.*M4A/ }).click();
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await expect(page.getByRole('region', { name: 'Grouping preview' })).toContainText('Reader One');
  await expect(page.getByRole('region', { name: 'Grouping preview' })).toContainText('Reader Two');
  await page.getByRole('button', { name: 'Confirm grouping', exact: true }).click();
  await expect(page.getByText(/Narrated by Reader One/)).toBeVisible();
  await expect(page.getByText(/Narrated by Reader Two/)).toBeVisible();
  await page.getByRole('button', { name: 'Group or separate formats' }).click();
  await page.getByRole('button', { name: 'Undo grouping or split' }).click();
});

test('audio persists through navigation, seeks, resumes and detects stale devices', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  const catalog = await (await page.request.get('/api/catalog?q=Listening%20Practice')).json();
  const work = catalog.items.find(
    (w: { editions: { representations: { format: string }[] }[] }) =>
      w.editions[0].representations[0].format === 'audio-set',
  );
  const representation = work.editions[0].representations[0];
  await page.goto(`/?book=${work.id}`);
  await page.getByRole('button', { name: 'Listen · AUDIO-SET', exact: true }).click();
  const player = page.getByRole('region', { name: 'Audiobook player' });
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Keep it safe.' })).toBeVisible();
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await player.getByRole('button', { name: 'Pause audio' }).click();
  await player.getByRole('combobox', { name: 'Speed', exact: true }).selectOption('1.5');
  await player.getByRole('combobox', { name: 'Jump to chapter' }).selectOption('10');
  const progress = async () =>
    (await (await page.request.get(`/api/representations/${representation.id}/playback`)).json())
      .progress;
  await expect.poll(async () => (await progress()).position).toBeGreaterThanOrEqual(10);
  await player.getByRole('slider', { name: 'Listening position' }).focus();
  await page.keyboard.press('ArrowLeft');
  await expect.poll(async () => (await progress()).position).toBeLessThan(10);
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Continue Listening Practice' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Continue Listening Practice' }).click();
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await player.getByRole('button', { name: 'Pause audio' }).click();
  await expect(player.getByRole('combobox', { name: 'Speed', exact: true })).toHaveValue('1.5');
  expect(
    Number(await player.getByRole('slider', { name: 'Listening position' }).inputValue()),
  ).toBeGreaterThan(9);
  // A second device saves after this player's last acknowledged revision.
  await expect.poll(async () => (await progress()).speed).toBe(1.5);
  await expect(player.getByText('Place saved', { exact: true })).toBeVisible();
  const current = await progress();
  const other = await page.request.patch(`/api/representations/${representation.id}/progress`, {
    headers: { 'X-Stacks-Request': '1' },
    data: { ...current, position: 15 },
  });
  expect(other.ok()).toBe(true);
  await player.getByRole('slider', { name: 'Listening position' }).focus();
  await page.keyboard.press('ArrowLeft');
  await expect(player.getByRole('alert')).toContainText('another device');
  await player.getByRole('button', { name: 'Reload saved position' }).click();
  await expect(player.getByRole('slider', { name: 'Listening position' })).toHaveValue('15');
  await player.getByRole('button', { name: 'Next track' }).click();
  await expect(player.getByRole('combobox', { name: 'Track', exact: true })).toHaveValue('1');
  await player.getByRole('button', { name: 'Previous track' }).click();
  await expect(player.getByRole('combobox', { name: 'Track', exact: true })).toHaveValue('0');
  await expect(player.getByRole('slider', { name: 'Listening position' })).toBeEnabled();
  await player.getByRole('slider', { name: 'Listening position' }).focus();
  await page.keyboard.press('End');
  await page.keyboard.press('ArrowLeft');
  await player.getByRole('button', { name: 'Play audio' }).click();
  await expect(player.getByRole('combobox', { name: 'Track', exact: true })).toHaveValue('1');
  await expect.poll(async () => (await progress()).completed).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('audio-player.png'), fullPage: true });
});
