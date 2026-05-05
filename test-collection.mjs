import { getCollection } from 'astro:content';

const blogEntries = await getCollection('blog');
console.log('Total blog entries:', blogEntries.length);
console.log('\nEntry slugs:');
blogEntries.forEach(entry => {
  console.log(`  - ${entry.slug}: ${entry.data.title}`);
});

const industrialEntry = blogEntries.find(e => e.slug === 'industrial-counselor');
if (industrialEntry) {
  console.log('\n✓ Found industrial-counselor entry');
} else {
  console.log('\n✗ industrial-counselor NOT found');
  console.log('\nAll available slugs:');
  blogEntries.forEach(e => console.log(`  ${e.slug}`));
}
