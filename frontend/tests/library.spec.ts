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
  await page.getByLabel('Issue or volume label').last().fill('Annual 2024');
  await page.getByLabel('Reading order').last().fill('2.5');
  await page.getByRole('button', { name: 'Save editions & series', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Organize editions & series' })).toBeVisible();
  await page.reload();
  await expect(
    page.getByText(new RegExp(`Reading Rooms · ${testInfo.project.name} · Annual 2024`)),
  ).toBeVisible();
  await expect(page.getByText('EBOOK · sl', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('editions-series.png'), fullPage: true });
});
