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
  await expect(
    page.getByRole('button', { name: 'Continue Listening Practice' }).first(),
  ).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Continue Listening Practice' }).first().click();
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await player.getByRole('button', { name: 'Pause audio' }).click();
  await expect(player.getByRole('combobox', { name: 'Speed', exact: true })).toHaveValue('1.5');
  expect(
    Number(await player.getByRole('slider', { name: 'Listening position' }).inputValue()),
  ).toBeGreaterThan(9);
  // Keep the old recording and its dirty position when a save fails during a switch.
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles('../backend/tests/fixtures/listening.m4b');
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByLabel('Search books or authors').fill('Listening Practice');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.locator('button.book').filter({ hasText: 'M4B' }).click();
  await page.getByRole('button', { name: 'Listen · M4B', exact: true }).waitFor();
  const saveRoute = `**/api/representations/${representation.id}/progress`;
  await page.route(saveRoute, (route) =>
    route.fulfill({ status: 503, json: { detail: 'Save unavailable' } }),
  );
  await player.getByRole('slider', { name: 'Listening position' }).focus();
  await page.keyboard.press('ArrowLeft');
  await expect(player.getByRole('alert')).toContainText('Save unavailable');
  const unsaved = await player.getByRole('slider', { name: 'Listening position' }).inputValue();
  await page.getByRole('button', { name: 'Listen · M4B', exact: true }).click();
  await expect(
    player.getByRole('combobox', { name: 'Track', exact: true }).locator('option'),
  ).toHaveCount(2);
  await expect(player.getByRole('slider', { name: 'Listening position' })).toHaveValue(unsaved);
  await page.unroute(saveRoute);
  await page.getByRole('button', { name: 'Listen · M4B', exact: true }).click();
  await expect(
    player.getByRole('combobox', { name: 'Track', exact: true }).locator('option'),
  ).toHaveCount(1);
  await expect.poll(async () => (await progress()).position).toBe(Number(unsaved));
  await page.goto(`/?book=${work.id}`);
  await page.getByRole('button', { name: 'Listen · AUDIO-SET', exact: true }).click();
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await player.getByRole('button', { name: 'Pause audio' }).click();
  // A second device saves after this player's last acknowledged revision.
  await expect.poll(async () => (await progress()).speed).toBe(1.5);
  await expect(player.getByText('Place saved', { exact: true })).toBeVisible();
  // Pause can still deliver a final save after its UI event. The second device
  // reloads a raced revision, just as a real client must, before taking ownership.
  await expect
    .poll(async () => {
      const current = await progress();
      const other = await page.request.patch(`/api/representations/${representation.id}/progress`, {
        headers: { 'X-Stacks-Request': '1' },
        data: { ...current, position: 15 },
      });
      if (other.status() === 409) return false;
      expect(other.status(), await other.text()).toBe(200);
      return true;
    })
    .toBe(true);
  const positionControl = player.getByRole('slider', { name: 'Listening position' });
  if (await positionControl.isEnabled()) {
    await positionControl.focus();
    await page.keyboard.press('ArrowLeft');
  }
  await expect(player.getByRole('alert')).toContainText('another device');
  await player.getByRole('button', { name: 'Reload saved position' }).click();
  await expect(player.getByRole('slider', { name: 'Listening position' })).toHaveValue('15');
  const playback = await (
    await page.request.get(`/api/representations/${representation.id}/playback`)
  ).json();
  const missingStream = `**/api/assets/${playback.tracks[1].asset_id}/stream`;
  await page.route(missingStream, (route) => route.fulfill({ status: 404 }));
  const beforeMissing = await progress();
  await player.getByRole('button', { name: 'Next track' }).click();
  await expect(player.getByRole('alert')).toContainText('could not be opened');
  expect(await progress()).toEqual(beforeMissing);
  await player.getByRole('button', { name: 'Previous track' }).click();
  await expect(player.getByRole('slider', { name: 'Listening position' })).toBeEnabled();
  await player.getByRole('button', { name: 'Next track' }).click();
  await expect(player.getByRole('alert')).toContainText('could not be opened');
  const beforeSignout = await progress();
  await page.getByRole('button', { name: /Sign out/ }).click();
  await expect(page.getByLabel('Library password')).toBeVisible();
  await page.unroute(missingStream);
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: work.title, exact: true })).toBeVisible();
  expect(await progress()).toEqual(beforeSignout);
  await page.getByRole('button', { name: 'Listen · AUDIO-SET', exact: true }).click();
  await expect(player.getByRole('button', { name: 'Pause audio' })).toBeVisible();
  await player.getByRole('button', { name: 'Pause audio' }).click();

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

test('personal shelves and repeated records survive reload and scope navigation', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve('../samples/The Long Way Home.epub'));
  await expect(page.getByRole('status')).toContainText(/added/);
  await page.getByRole('combobox', { name: 'Library scope' }).selectOption('all');
  await page.getByLabel('Search books or authors').fill('The Long Way Home');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Open The Long Way Home', exact: true }).click();
  const personal = page.getByRole('region', { name: 'Personal library details' });
  const workId = new URL(page.url()).searchParams.get('book');
  const beforeCount = (await (await page.request.get(`/api/works/${workId}/records`)).json()).total;
  await personal.getByRole('button', { name: 'Edit personal details' }).click();
  await personal.getByRole('combobox', { name: 'Shelf', exact: true }).selectOption('archive');
  await personal.getByRole('combobox', { name: 'Rating', exact: true }).selectOption('4');
  await personal.getByLabel('Tags, separated by commas').fill('summer, return to');
  await personal
    .getByLabel('Personal notes')
    .fill('For a long afternoon. Keep the original edition.');
  await personal.getByRole('button', { name: 'Save personal details' }).click();
  await expect(personal.getByRole('status')).toContainText('Personal details saved');
  for (const kind of ['read', 'listen']) {
    await personal.getByRole('button', { name: 'Add reading record' }).click();
    await personal.getByRole('combobox', { name: 'Activity', exact: true }).selectOption(kind);
    await personal.getByLabel('Started', { exact: true }).fill('2026-08-01');
    await personal.getByLabel('Finished (optional)').fill('2026-08-15');
    await personal.getByRole('button', { name: 'Save reading record' }).click();
    await expect(personal.getByRole('status')).toContainText('Reading record saved');
  }
  await page.reload();
  await expect(personal.getByText('In your archive · Your choice · 4 / 5')).toBeVisible();
  await expect(
    personal.getByText('For a long afternoon. Keep the original edition.'),
  ).toBeVisible();
  await expect(personal.locator('li')).toHaveCount(Math.min(beforeCount + 2, 5));
  expect((await (await page.request.get(`/api/works/${workId}/records`)).json()).total).toBe(
    beforeCount + 2,
  );
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await page.getByRole('combobox', { name: 'Library scope' }).selectOption('library');
  await expect(
    page.getByRole('button', { name: 'Open The Long Way Home', exact: true }),
  ).toBeHidden();
  await page.getByRole('combobox', { name: 'Library scope' }).selectOption('archive');
  await expect(
    page.getByRole('button', { name: 'Open The Long Way Home', exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Library scope' })).toHaveValue('archive');
  await page.getByRole('button', { name: 'Open The Long Way Home', exact: true }).click();
  await page.getByRole('button', { name: 'Back to library' }).click();
  await expect(page.getByRole('combobox', { name: 'Library scope' })).toHaveValue('archive');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('button', { name: 'Open The Long Way Home', exact: true }).click();
  await personal.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('personal-library.png'), fullPage: true });
});

test('archiving the final book on a page returns to the last populated page', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  const prefix = `Shelf Test ${testInfo.project.name}`;
  await page
    .getByLabel('Choose publications')
    .setInputFiles(
      Array.from({ length: 25 }, (_, i) =>
        path.resolve(`../samples/${prefix} ${String(i).padStart(2, '0')}.epub`),
      ),
    );
  await expect(page.getByRole('status')).toContainText('25 books added');
  await page.getByLabel('Search books or authors').fill(prefix);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(page).toHaveURL(/offset=24/);
  await page.locator('button.book').click();
  const personal = page.getByRole('region', { name: 'Personal library details' });
  await personal.getByRole('button', { name: 'Edit personal details' }).click();
  await personal.getByRole('combobox', { name: 'Shelf', exact: true }).selectOption('archive');
  await personal.getByRole('button', { name: 'Save personal details' }).click();
  await expect(personal.getByRole('status')).toContainText('Personal details saved');
  await expect(page).not.toHaveURL(/offset=/);
  await expect(page).toHaveURL(/book=/);
  await page.getByRole('button', { name: 'Back to library' }).click();
  await expect(page.locator('button.book')).toHaveCount(24);
  await page.reload();
  await expect(page.locator('button.book')).toHaveCount(24);
  // An invalid empty-result deep link also normalizes its offset.
  await page.goto('/?q=nothing-owned-with-this-name&offset=240');
  await expect(page.getByRole('heading', { name: 'No books found.' })).toBeVisible();
  await expect(page).not.toHaveURL(/offset=/);
});

test('comic runs stay distinct, ordered, followed, and available through Home', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  await page
    .getByRole('group', { name: 'Publication type' })
    .getByRole('button', { name: 'Comics', exact: true })
    .click();
  const runs = page.getByRole('region', { name: 'Comic runs' });
  await expect(
    runs.getByRole('button', { name: 'Open run Orbit 1999', exact: true }),
  ).toBeVisible();
  await expect(
    runs.getByRole('button', { name: 'Open run Orbit 2026', exact: true }),
  ).toBeVisible();
  await runs.getByRole('button', { name: 'Open run Orbit 1999', exact: true }).click();
  await expect(page).toHaveURL(/series=/);
  await expect(runs.locator('button.book').first()).toHaveAttribute('aria-label', 'Open Orbit 01');
  await expect(runs.locator('button.book').nth(1)).toHaveAttribute(
    'aria-label',
    'Open Orbit Annual',
  );
  await runs.getByRole('button', { name: 'Next issues →', exact: true }).click();
  await expect(page).toHaveURL(/offset=24/);
  await expect(runs.locator('button.book')).toHaveCount(2);
  await runs.locator('button.book').first().click();
  await page.getByRole('button', { name: 'Back to library' }).click();
  await expect(runs.locator('button.book')).toHaveCount(2);
  await page.reload();
  await expect(runs.locator('button.book')).toHaveCount(2);
  // Restore a deliberate follow state for each viewport's independent session.
  const unfollow = runs.getByRole('button', { name: 'Unfollow series', exact: true });
  if (await unfollow.isVisible()) await unfollow.click();
  await runs.getByRole('button', { name: 'Follow series', exact: true }).click();
  await expect(runs.getByRole('button', { name: 'Unfollow series', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  const next = page.getByRole('region', { name: 'Next in followed series' });
  await expect(next.getByRole('button', { name: 'Open next Orbit 01', exact: true })).toBeVisible();
  await next.getByRole('button', { name: 'Open next Orbit 01', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Orbit 01', exact: true })).toBeVisible();
  const originalUrl = page.url();
  const personal = page.getByRole('region', { name: 'Personal library details' });
  await personal.getByRole('button', { name: 'Add reading record' }).click();
  await personal.getByLabel('Started', { exact: true }).fill('2026-09-01');
  await personal.getByLabel('Finished (optional)').fill('2026-09-02');
  await personal.getByRole('button', { name: 'Save reading record' }).click();
  await expect(personal.getByRole('status')).toContainText('Reading record saved');
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(
    next.getByRole('button', { name: 'Open next Orbit Annual', exact: true }),
  ).toBeVisible();
  await page.goto(originalUrl);
  await personal
    .getByRole('button', { name: 'Remove record from 2026-09-01', exact: true })
    .click();
  await expect(personal.getByRole('status')).toContainText('Reading record removed');
  await page.getByRole('button', { name: 'Back to library' }).click();
  await runs.getByRole('button', { name: 'All comic runs' }).click();
  await runs.getByRole('button', { name: 'Comics without a series' }).click();
  await expect(
    page.getByRole('button', { name: 'Open A Standalone Comic', exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/unassigned=1/);
  await page.getByRole('button', { name: 'All comic runs' }).click();
  await expect(
    runs.getByRole('button', { name: 'Open run Orbit 2026', exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('comic-runs.png'), fullPage: true });
});

test('new run search and shelf filters reset run paging while back preserves it', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  const work = (await (await page.request.get('/api/catalog?q=Orbit%2001')).json()).items[0];
  const prefix = `ZZ Slice ${testInfo.project.name}`;
  const memberships = [...work.memberships];
  for (let index = 0; index < 30; index++) {
    const response = await page.request.post('/api/series', {
      headers: { 'X-Stacks-Request': '1' },
      data: { name: `${prefix} ${String(index).padStart(2, '0')}`, run: '2026' },
    });
    expect(response.ok()).toBe(true);
    memberships.push({ series_id: (await response.json()).id, position: 1, designation: '#1' });
  }
  const edited = await page.request.patch(`/api/works/${work.id}`, {
    headers: { 'X-Stacks-Request': '1' },
    data: { ...work, memberships },
  });
  expect(edited.ok()).toBe(true);
  await page
    .getByRole('group', { name: 'Publication type' })
    .getByRole('button', { name: 'Comics', exact: true })
    .click();
  const runs = page.getByRole('region', { name: 'Comic runs' });
  await runs.getByRole('button', { name: 'Next runs →', exact: true }).click();
  await expect(page).toHaveURL(/run_offset=24/);
  await page.getByLabel('Search comic runs').fill(prefix);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).not.toHaveURL(/run_offset=/);
  const first = runs.getByRole('button', { name: `Open run ${prefix} 00 2026`, exact: true });
  await expect(first).toBeVisible();
  await runs.getByRole('button', { name: 'Next runs →', exact: true }).click();
  await expect(page).toHaveURL(/run_offset=24/);
  await page.getByRole('combobox', { name: 'Library scope' }).selectOption('all');
  await expect(page).not.toHaveURL(/run_offset=/);
  await expect(first).toBeVisible();
  await runs.getByRole('button', { name: 'Next runs →', exact: true }).click();
  await expect(runs.locator('.run-card')).toHaveCount(6);
  await runs.locator('.run-card').first().click();
  await runs.getByRole('button', { name: 'All comic runs' }).click();
  await expect(page).toHaveURL(/run_offset=24/);
  await page.reload();
  await expect(runs.locator('.run-card')).toHaveCount(6);
});

test('collections keep a cross-page order, details context, and Home choices', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByRole('button', { name: 'Collections', exact: true }).click();
  const name = `Weekend reading ${testInfo.project.name}`;
  await page.getByLabel('New collection name').fill(name);
  await page.getByLabel('Show next unfinished Library work on Home').check();
  await page.getByRole('button', { name: 'Create collection', exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Find', exact: true }).selectOption('series');
  await page.getByLabel('Search your library', { exact: true }).fill('Orbit');
  await page.getByRole('button', { name: 'Search to add' }).click();
  await page.getByRole('button', { name: 'Add series Orbit 1999', exact: true }).click();
  await expect(page.getByRole('heading', { name: '26 works, your order.' })).toBeVisible();
  await page.getByRole('button', { name: 'Next works →', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open Orbit 24', exact: true })).toBeVisible();
  const move = page.getByRole('button', { name: 'Move Orbit 24 up', exact: true });
  await move.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Open Orbit 23', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open Orbit 23', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Orbit 23', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '← Back to collection', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open Orbit 23', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '← Previous works', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open Orbit 24', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Find', exact: true }).selectOption('works');
  await page.getByLabel('Search your library', { exact: true }).fill('Listening Practice');
  await page.getByRole('button', { name: 'Search to add' }).click();
  await page
    .getByRole('group', { name: 'Match Listening Practice', exact: true })
    .filter({ hasText: '2 files' })
    .getByRole('button', { name: 'Add Listening Practice to collection', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: '27 works, your order.' })).toBeVisible();
  // Repeated additions never duplicate a work or alter its order.
  await page
    .getByRole('group', { name: 'Match Listening Practice', exact: true })
    .filter({ hasText: '2 files' })
    .getByRole('button', { name: 'Add Listening Practice to collection', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'Save collection', exact: true })).toBeEnabled();
  await expect(page.getByRole('heading', { name: '27 works, your order.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('collection.png'), fullPage: true });
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'From your collections.' })).toBeVisible();
  const homeSection = page.getByRole('region', { name: 'Next in collections', exact: true });
  await homeSection
    .getByRole('button', { name: 'Open collection next Orbit 01', exact: true })
    .filter({ hasText: name })
    .click();
  await page.getByRole('button', { name: '← Back to collection', exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  // A second client editing the same collection is protected by its revision.
  const collectionId = new URL(page.url()).searchParams.get('collection')!;
  const current = (await (await page.request.get(`/api/collections/${collectionId}/works`)).json())
    .collection;
  const changed = await page.request.patch(`/api/collections/${collectionId}`, {
    headers: { 'X-Stacks-Request': '1' },
    data: { ...current, name: name + ' revised' },
  });
  expect(changed.status()).toBe(200);
  await page.getByLabel('Collection name', { exact: true }).fill(name + ' stale');
  await page.getByRole('button', { name: 'Save collection', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('This collection changed');
  await page.getByRole('button', { name: 'Reload collection', exact: true }).click();
  await expect(page.getByRole('heading', { name: name + ' revised', exact: true })).toBeVisible();
});

test('collection history navigation disables edits until the requested identity loads', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await expect(page.getByRole('heading', { name: 'Good books.' })).toBeVisible();
  const collections = [];
  for (const suffix of ['A', 'B']) {
    const response = await page.request.post('/api/collections', {
      headers: { 'X-Stacks-Request': '1' },
      data: { name: `Navigation ${testInfo.project.name} ${suffix}` },
    });
    expect(response.status()).toBe(200);
    collections.push(await response.json());
  }
  const [first, second] = collections;
  expect(first.revision).toBe(second.revision);
  await page.goto(`/?view=collections&collection=${first.id}`);
  await expect(page.getByRole('heading', { name: first.name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: '← All collections', exact: true }).click();
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: second.name, exact: true }) })
    .click();
  await expect(page.getByRole('heading', { name: second.name, exact: true })).toBeVisible();
  // Browser history retains the list entry between A and B. Delay B on Forward.
  await page.goBack();
  await expect(page.getByLabel('New collection name')).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: first.name, exact: true })).toBeVisible();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested!: () => void;
  const incoming = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route(`**/api/collections/${second.id}/works*`, async (route) => {
    requested();
    await gate;
    await route.continue();
  });
  await page.goForward();
  await page.goForward();
  await incoming;
  await expect(page.getByRole('button', { name: 'Save collection', exact: true })).toBeDisabled();
  await expect(page.getByLabel('Collection name', { exact: true })).toBeDisabled();
  await expect(page.getByRole('region', { name: 'Collection contents' })).toHaveCount(0);
  release();
  await expect(page.getByRole('heading', { name: second.name, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save collection', exact: true })).toBeEnabled();
  const unchanged = (await (await page.request.get(`/api/collections/${second.id}/works`)).json())
    .collection;
  expect(unchanged.name).toBe(second.name);
  expect(unchanged.revision).toBe(second.revision);
});

test('register an original in Archive and explain external backup protection', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const sources = page.getByRole('region', { name: 'Read-only sources', exact: true });
  await expect(sources).toContainText('Protect source originals separately.');
  await sources.getByLabel('Source', { exact: true }).selectOption('sample');
  await sources
    .getByLabel('Paths within this source')
    .fill(`Registered ${testInfo.project.name}.epub`);
  await sources.getByRole('button', { name: 'Register originals', exact: true }).click();
  await expect(sources.getByRole('status')).toContainText('Registered in Archive.');
  await sources.getByRole('button', { name: 'Open registered work' }).click();
  await expect(
    page.getByRole('heading', { name: `A registered book ${testInfo.project.name}`, exact: true }),
  ).toBeVisible();
  const originals = page.getByRole('region', { name: 'Original availability', exact: true });
  await expect(originals).toContainText('Registered in sample');
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download EPUB' }).click();
  expect((await download).suggestedFilename()).toBe(`Registered ${testInfo.project.name}.epub`);
  await page.reload();
  await expect(originals).toContainText('Registered in sample');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Library backup', exact: true })).toBeVisible();
  await expect(
    page.getByText('Registered source originals are not included;', { exact: false }),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('sources.png'), fullPage: true });
});

test('Inbox scans sources without importing and preserves paged review across navigation', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByRole('button', { name: 'Inbox', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Inbox.', exact: true })).toBeVisible();
  await page.getByLabel('Source', { exact: true }).selectOption('sample');
  await page.getByLabel('Folder within source').fill(`Inbox ${testInfo.project.name}`);
  const before = (await (await page.request.get('/api/catalog?scope=all')).json()).total;
  await page.getByRole('button', { name: 'Scan source', exact: true }).click();
  const jobs = page.getByRole('region', { name: 'Scan jobs', exact: true });
  await expect(jobs).toContainText('26 inspected', { timeout: 20000 });
  const files = page.getByRole('region', { name: 'Discovered files', exact: true });
  await expect(files).toContainText('26 files in this scan');
  await files.getByRole('button', { name: 'Next files', exact: true }).click();
  await expect(page).toHaveURL(/inbox_offset=24/);
  await expect(
    files.getByRole('heading', { name: `Inbox ${testInfo.project.name} 24`, exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    files.getByRole('heading', { name: `Inbox ${testInfo.project.name} 25`, exact: true }),
  ).toBeVisible();
  await files.getByRole('button', { name: 'Previous files', exact: true }).click();
  await expect(
    files.getByRole('heading', { name: `Inbox ${testInfo.project.name} 00`, exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    files.getByRole('heading', { name: `Inbox ${testInfo.project.name} 24`, exact: true }),
  ).toBeVisible();
  await files.getByText('Inspection evidence', { exact: true }).first().click();
  await expect(files).toContainText('SHA-256');
  expect((await (await page.request.get('/api/catalog?scope=all')).json()).total).toBe(before);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('inbox.png'), fullPage: true });
});

test('preview edited Inbox files, reload, then accept verified originals', async ({
  page,
}, testInfo) => {
  const viewport = testInfo.project.name;
  await page.goto('/?view=inbox');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByLabel('Source', { exact: true }).selectOption('sample');
  await page.getByLabel('Folder within source').fill(`Acceptance ${viewport}`);
  await page.getByRole('button', { name: 'Scan source', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Scan jobs', exact: true })).toContainText(
    '3 inspected',
  );
  await page
    .getByRole('checkbox', { name: `Select Acceptance ${viewport}/0.epub`, exact: true })
    .check();
  await page
    .getByRole('checkbox', { name: `Select Acceptance ${viewport}/1.epub`, exact: true })
    .check();
  const files = page.getByRole('region', { name: 'Discovered files', exact: true });
  const first = files
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: `Acceptance ${viewport} 0`, exact: true }) });
  await first.getByRole('button', { name: 'Edit acceptance metadata', exact: true }).click();
  await page.getByLabel('Accepted title', { exact: true }).fill(`Chosen ${viewport} title`);
  await page.getByRole('button', { name: 'Save acceptance metadata', exact: true }).click();
  const acceptance = page.getByRole('region', { name: 'Batch acceptance', exact: true });
  await acceptance
    .getByLabel('Original storage')
    .selectOption(viewport === 'desktop' ? 'copy' : 'register');
  await acceptance.getByLabel('Batch shelf').selectOption('library');
  await acceptance.getByText('Shared metadata and audio grouping', { exact: true }).click();
  await acceptance
    .getByLabel('Batch authors (one per line)', { exact: true })
    .fill(`Batch author ${viewport}`);
  let chosenRun = '';
  for (let index = 0; index < 21; index++) {
    const response = await page.request.post('/api/series', {
      headers: { 'X-Stacks-Request': '1' },
      data: { name: `Acceptance runs ${viewport}`, run: String(index).padStart(2, '0') },
    });
    expect(response.ok()).toBe(true);
    if (index === 20) chosenRun = (await response.json()).id;
  }
  await acceptance.getByLabel('Find an existing run').fill(`Acceptance runs ${viewport}`);
  await acceptance.getByRole('button', { name: 'Find runs', exact: true }).click();
  await acceptance.getByRole('button', { name: 'Next runs', exact: true }).click();
  await acceptance.getByLabel('Batch series/run').selectOption(chosenRun);
  await acceptance.getByRole('button', { name: 'Previous runs', exact: true }).click();
  await expect(acceptance.getByLabel('Batch series/run')).toHaveValue(chosenRun);
  await acceptance.getByRole('button', { name: 'Preview 2 selected files', exact: true }).click();
  const preview = page.getByRole('region', { name: 'Acceptance preview', exact: true });
  await expect(preview).toContainText(`Chosen ${viewport} title`);
  await expect(preview).toContainText(`Batch author ${viewport}`);
  await expect(preview).toContainText(`Acceptance runs ${viewport} · 20`);
  await page.reload();
  await expect(preview).toContainText(`Chosen ${viewport} title`);
  await preview.getByRole('button', { name: 'Confirm acceptance', exact: true }).click();
  await expect(preview).toContainText('2 accepted', { timeout: 15000 });
  const catalog = await (
    await page.request.get(
      `/api/catalog?scope=all&q=${encodeURIComponent(`Batch author ${viewport}`)}`,
    )
  ).json();
  expect(catalog.total).toBe(2);
  expect(
    catalog.items.every(
      (work: { personal: { shelf: string } }) => work.personal.shelf === 'library',
    ),
  ).toBe(true);
  expect(catalog.items[0].editions[0].representations[0].assets[0].root).toBe(
    viewport === 'desktop' ? 'managed' : 'sample',
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('acceptance.png'), fullPage: true });
  const batchUrl = page.url();
  await page.evaluate(() => {
    (window as unknown as { stacksNavigationMarker: boolean }).stacksNavigationMarker = true;
  });
  await preview.getByRole('link', { name: 'Open accepted work', exact: true }).first().click();
  await expect(
    page.getByRole('heading', { name: `Chosen ${viewport} title`, exact: true, level: 1 }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { stacksNavigationMarker: boolean }).stacksNavigationMarker,
    ),
  ).toBe(true);
  await page.goBack();
  await expect(page).toHaveURL(batchUrl);
  await expect(preview).toContainText('2 accepted');
  // Leaving while a work request is pending must win over its late response.
  const workId = catalog.items.find(
    (work: { title: string }) => work.title === `Chosen ${viewport} title`,
  ).id;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested!: () => void;
  const incoming = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route(`**/api/works/${workId}`, async (route) => {
    requested();
    await gate;
    await route.continue();
  });
  const response = page.waitForResponse((result) => result.url().endsWith(`/api/works/${workId}`));
  await preview.getByRole('link', { name: 'Open accepted work', exact: true }).first().click();
  await incoming;
  await page.goBack();
  const previous = page.url();
  release();
  await (await response).finished();
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  await expect(page).toHaveURL(previous);
  await expect(page.getByRole('heading', { name: 'Inbox.', exact: true, level: 1 })).toBeVisible();
});

test('review selected audio tracks in natural disc order before acceptance', async ({
  page,
}, testInfo) => {
  const viewport = testInfo.project.name;
  await page.goto('/?view=inbox');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByLabel('Source', { exact: true }).selectOption('sample');
  await page.getByLabel('Folder within source').fill(`Audio inbox ${viewport}`);
  await page.getByRole('button', { name: 'Scan source', exact: true }).click();
  const files = page.getByRole('region', { name: 'Discovered files', exact: true });
  await expect(files).toContainText('2 files in this scan');
  for (const disc of [10, 2])
    await page
      .getByRole('checkbox', {
        name: `Select Audio inbox ${viewport}/Disc ${disc}/track.mp3`,
        exact: true,
      })
      .check();
  const acceptance = page.getByRole('region', { name: 'Batch acceptance', exact: true });
  await acceptance.getByText('Shared metadata and audio grouping', { exact: true }).click();
  await acceptance
    .getByLabel('Batch title (optional)', { exact: true })
    .fill(`Reviewed audio ${viewport}`);
  await acceptance
    .getByRole('checkbox', { name: 'Group selected audio tracks as one recording', exact: true })
    .check();
  await acceptance.getByRole('button', { name: 'Preview 2 selected files', exact: true }).click();
  const preview = page.getByRole('region', { name: 'Acceptance preview', exact: true });
  await expect(
    preview.getByRole('heading', { name: 'One reviewed recording', exact: true }),
  ).toBeVisible();
  await expect(preview.locator('li').first()).toContainText('Disc 2/track.mp3');
  await expect(preview.locator('li').nth(1)).toContainText('Disc 10/track.mp3');
  await preview.getByRole('button', { name: 'Confirm acceptance', exact: true }).click();
  await expect(preview).toContainText('2 accepted', { timeout: 15000 });
  await preview.getByRole('link', { name: 'Open accepted work', exact: true }).first().click();
  await expect(
    page.getByRole('heading', { name: `Reviewed audio ${viewport}`, exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Listen · AUDIO-SET', exact: true })).toBeVisible();
});

test('remove deliberately, inspect paginated Trash, and restore the original', async ({
  page,
}, testInfo) => {
  const viewport = testInfo.project.name;
  const title = `Trash journey ${viewport}`;
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve(`../samples/${title}.epub`));
  await expect(page.getByRole('status')).toContainText('added');
  await page.getByLabel('Search books or authors').fill(title);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${title}`, exact: true }).click();
  const workUrl = page.url();
  const downloadUrl = await page.getByRole('link', { name: /^Download EPUB/ }).getAttribute('href');
  const original = await (await page.request.get(downloadUrl!)).body();
  await page.getByText('Remove from your catalog', { exact: true }).click();
  await page.getByRole('button', { name: 'Move to Trash', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'In Trash', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Restore book', exact: true })).toBeVisible();
  expect((await page.request.get(downloadUrl!)).status()).toBe(409);
  await page.getByRole('button', { name: 'Trash', exact: true }).click();
  await page.getByLabel('Search Trash', { exact: true }).fill(`Recovery shelf ${viewport}`);
  await page.getByRole('button', { name: 'Search Trash', exact: true }).click();
  await expect(page.getByText('13 books in Trash', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next trashed books', exact: true }).click();
  await expect(page).toHaveURL(/trash_offset=12/);
  const pagedUrl = page.url();
  await page.reload();
  await expect(page.getByText('13 books in Trash', { exact: true })).toBeVisible();
  const entry = page.locator('.entries article').first();
  const lastTitle = await entry.getByRole('button').first().innerText();
  await entry.getByRole('button', { name: lastTitle, exact: true }).click();
  await expect(page.getByRole('heading', { name: lastTitle, exact: true, level: 1 })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(pagedUrl);
  await expect(page.locator('.entries article')).toHaveCount(1);
  await page.screenshot({ path: testInfo.outputPath('trash.png'), fullPage: true });
  await page
    .locator('.entries article')
    .getByRole('button', { name: 'Restore book', exact: true })
    .click();
  await expect(page.getByText('12 books in Trash', { exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/trash_offset=12/);
  await page.goto(workUrl);
  await page.getByRole('button', { name: 'Restore book', exact: true }).click();
  await expect(page.getByRole('link', { name: /^Download EPUB/ })).toBeVisible();
  expect(await (await page.request.get(downloadUrl!)).body()).toEqual(original);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('removing a regrouped playing audiobook saves and releases its player', async ({
  page,
}, testInfo) => {
  const title = `Trash audio ${testInfo.project.name}`;
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles([
      path.resolve(`../samples/Trash audio target ${testInfo.project.name}.epub`),
      path.resolve(`../samples/${title}.m4b`),
    ]);
  await expect(page.getByRole('status')).toContainText('added');
  await page.getByLabel('Search books or authors').fill(title);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${title}`, exact: true }).click();
  await page.getByRole('button', { name: 'Listen · M4B', exact: true }).click();
  const player = page.getByRole('region', { name: 'Audiobook player', exact: true });
  await expect(player.getByRole('button', { name: 'Pause audio', exact: true })).toBeVisible();
  await player.getByRole('slider', { name: 'Listening position' }).focus();
  await page.keyboard.press('ArrowRight');
  const sourceId = new URL(page.url()).searchParams.get('book');
  const targetTitle = `Trash audio target ${testInfo.project.name}`;
  const target = (
    await (await page.request.get(`/api/catalog?q=${encodeURIComponent(targetTitle)}`)).json()
  ).items[0];
  const planned = await page.request.post('/api/operations/preview', {
    headers: { 'X-Stacks-Request': '1' },
    data: { mode: 'editions', source_work_id: sourceId, target_work_id: target.id },
  });
  expect(planned.ok()).toBe(true);
  const plan = await planned.json();
  const grouped = await page.request.post(`/api/operations/${plan.id}/commit`, {
    headers: { 'X-Stacks-Request': '1' },
    data: {
      resolutions: Object.fromEntries(
        plan.conflicts.map((conflict: { field: string }) => [conflict.field, 'target']),
      ),
    },
  });
  expect(grouped.ok()).toBe(true);
  // Navigate through the UI so the player deliberately keeps its cached pre-group work ID.
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await page.getByLabel('Search books or authors').fill(targetTitle);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${targetTitle}`, exact: true }).click();
  await expect(player).toBeVisible();
  await page.getByText('Remove from your catalog', { exact: true }).click();
  await page.getByRole('button', { name: 'Move to Trash', exact: true }).click();
  await expect(player).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restore book', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Restore book', exact: true }).click();
  await page.getByRole('button', { name: 'Listen · M4B', exact: true }).click();
  await expect(player.getByRole('button', { name: 'Pause audio', exact: true })).toBeVisible();
  const position = Number(
    await player.getByRole('slider', { name: 'Listening position' }).inputValue(),
  );
  expect(position).toBeGreaterThan(0);
});

test('connect and revoke a reader without sharing owner access', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const name = `Reading tablet ${testInfo.project.name}`;
  await page.getByLabel('Reader name', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Create reader password' }).click();
  const password = page.getByLabel('Reader password', { exact: true });
  await expect(password).toBeVisible();
  const secret = await password.inputValue();
  const url = await page.getByLabel('Catalog URL', { exact: true }).inputValue();
  const authorization = `Basic ${Buffer.from(`stacks:${secret}`).toString('base64')}`;
  const feed = await page.request.get(url, { headers: { Authorization: authorization } });
  expect(feed.status()).toBe(200);
  expect(feed.headers()['content-type']).toContain('kind=navigation');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('button', { name: 'I saved the password' }).click();
  await expect(password).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Reader devices')).toContainText(name);
  await expect(password).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('reader-devices.png'), fullPage: true });
  await page.getByRole('button', { name: `Revoke ${name}`, exact: true }).click();
  await expect(page.getByRole('button', { name: `Revoke ${name}`, exact: true })).toHaveCount(0);
  expect(
    (await page.request.get(url, { headers: { Authorization: authorization } })).status(),
  ).toBe(401);
});

test('preview, choose, reload and reset a custom cover', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  const title = `Cover selection ${testInfo.project.name}`;
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve(`../samples/${title}.epub`));
  await expect(page.getByRole('status')).toContainText('added');
  await page.getByLabel('Search books or authors').fill(title);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${title}`, exact: true }).click();
  const work = { id: new URL(page.url()).searchParams.get('book') };
  await page.getByText('Choose a cover', { exact: true }).click();
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=',
    'base64',
  );
  await page
    .getByLabel('Cover image', { exact: true })
    .setInputFiles({ name: 'my-cover.png', mimeType: 'image/png', buffer: png });
  await expect(page.getByAltText('Preview of your chosen cover')).toBeVisible();
  await page.getByRole('button', { name: 'Use this cover', exact: true }).click();
  await expect(page.getByText('Chosen by you', { exact: true })).toBeVisible();
  const selected = (await (await page.request.get(`/api/works/${work.id}`)).json())
    .selected_cover_id;
  expect(selected).toBeTruthy();
  await page.reload();
  await page.getByText('Choose a cover', { exact: true }).click();
  await expect(page.getByText('Chosen by you', { exact: true })).toBeVisible();
  const image = page.getByAltText(`Cover of ${title}`);
  await expect(image).toHaveAttribute('src', new RegExp(selected));
  const downloaded = await page.request.get(`/api/works/${work.id}/cover/original`);
  expect(await downloaded.body()).toEqual(png);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('chosen-cover.png'), fullPage: true });
  await page.getByRole('button', { name: 'Use embedded cover', exact: true }).click();
  await expect(page.getByText('Chosen by you', { exact: true })).toHaveCount(0);
  expect(
    (await (await page.request.get(`/api/works/${work.id}`)).json()).selected_cover_id,
  ).toBeNull();
});

test('review provider fields while preserving a manual title', async ({ page }, testInfo) => {
  const title = `Metadata ${testInfo.project.name}`;
  await page.goto('/');
  await page.getByLabel('Library password').fill('browser-test-password');
  await page.getByRole('button', { name: 'Open my library' }).click();
  await page
    .getByLabel('Choose publications')
    .setInputFiles(path.resolve(`../samples/${title}.epub`));
  await expect(page.getByRole('status')).toContainText('added');
  await page.getByLabel('Search books or authors').fill(title);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: `Open ${title}`, exact: true }).click();
  await page.getByRole('button', { name: 'Edit details' }).click();
  const corrected = `${title} corrected`;
  await page.getByLabel('Title', { exact: true }).fill(corrected);
  await page.getByRole('button', { name: 'Save details' }).click();
  await page.getByText('Find book details', { exact: true }).click();
  await page.getByLabel('Title or author to look up').fill(title);
  await page.getByRole('button', { name: 'Search Open Library' }).click();
  await page.getByRole('button', { name: 'Next matches', exact: true }).click();
  await page.getByRole('button', { name: `Review ${title} suggested 6`, exact: true }).click();
  const preview = page.getByRole('region', { name: 'Metadata preview', exact: true });
  await expect(preview.getByLabel('Use suggested title', { exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: 'Look up description', exact: true }).click();
  await expect(preview.getByLabel('Use suggested description', { exact: true })).toBeChecked();
  await preview.getByLabel('Use suggested authors', { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Accept selected fields', exact: true }).click();
  await expect(page.getByRole('heading', { name: corrected, exact: true })).toBeVisible();
  await expect(
    page.getByText('A description from the test catalog.', { exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.getByText('Find book details', { exact: true }).click();
  await page.getByLabel('Title or author to look up').fill(title);
  await page.getByRole('button', { name: 'Search Open Library' }).click();
  await page.getByRole('button', { name: `Review ${title} suggested 1`, exact: true }).click();
  await preview.getByLabel('Use suggested title', { exact: true }).check();
  await expect(
    page.getByRole('button', { name: 'Accept selected fields', exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel('Replace my protected title with these suggestions', { exact: true })
    .check();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('metadata-preview.png'), fullPage: true });
  await page.getByRole('button', { name: 'Accept selected fields', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: `${title} suggested 1`, exact: true }),
  ).toBeVisible();
});
