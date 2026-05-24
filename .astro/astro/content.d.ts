declare module 'astro:content' {
	interface Render {
		'.mdx': Promise<{
			Content: import('astro').MarkdownInstance<{}>['Content'];
			headings: import('astro').MarkdownHeading[];
			remarkPluginFrontmatter: Record<string, any>;
			components: import('astro').MDXInstance<{}>['components'];
		}>;
	}
}

declare module 'astro:content' {
	interface RenderResult {
		Content: import('astro/runtime/server/index.js').AstroComponentFactory;
		headings: import('astro').MarkdownHeading[];
		remarkPluginFrontmatter: Record<string, any>;
	}
	interface Render {
		'.md': Promise<RenderResult>;
	}

	export interface RenderedContent {
		html: string;
		metadata?: {
			imagePaths: Array<string>;
			[key: string]: unknown;
		};
	}
}

declare module 'astro:content' {
	type Flatten<T> = T extends { [K: string]: infer U } ? U : never;

	export type CollectionKey = keyof AnyEntryMap;
	export type CollectionEntry<C extends CollectionKey> = Flatten<AnyEntryMap[C]>;

	export type ContentCollectionKey = keyof ContentEntryMap;
	export type DataCollectionKey = keyof DataEntryMap;

	type AllValuesOf<T> = T extends any ? T[keyof T] : never;
	type ValidContentEntrySlug<C extends keyof ContentEntryMap> = AllValuesOf<
		ContentEntryMap[C]
	>['slug'];

	/** @deprecated Use `getEntry` instead. */
	export function getEntryBySlug<
		C extends keyof ContentEntryMap,
		E extends ValidContentEntrySlug<C> | (string & {}),
	>(
		collection: C,
		// Note that this has to accept a regular string too, for SSR
		entrySlug: E,
	): E extends ValidContentEntrySlug<C>
		? Promise<CollectionEntry<C>>
		: Promise<CollectionEntry<C> | undefined>;

	/** @deprecated Use `getEntry` instead. */
	export function getDataEntryById<C extends keyof DataEntryMap, E extends keyof DataEntryMap[C]>(
		collection: C,
		entryId: E,
	): Promise<CollectionEntry<C>>;

	export function getCollection<C extends keyof AnyEntryMap, E extends CollectionEntry<C>>(
		collection: C,
		filter?: (entry: CollectionEntry<C>) => entry is E,
	): Promise<E[]>;
	export function getCollection<C extends keyof AnyEntryMap>(
		collection: C,
		filter?: (entry: CollectionEntry<C>) => unknown,
	): Promise<CollectionEntry<C>[]>;

	export function getEntry<
		C extends keyof ContentEntryMap,
		E extends ValidContentEntrySlug<C> | (string & {}),
	>(entry: {
		collection: C;
		slug: E;
	}): E extends ValidContentEntrySlug<C>
		? Promise<CollectionEntry<C>>
		: Promise<CollectionEntry<C> | undefined>;
	export function getEntry<
		C extends keyof DataEntryMap,
		E extends keyof DataEntryMap[C] | (string & {}),
	>(entry: {
		collection: C;
		id: E;
	}): E extends keyof DataEntryMap[C]
		? Promise<DataEntryMap[C][E]>
		: Promise<CollectionEntry<C> | undefined>;
	export function getEntry<
		C extends keyof ContentEntryMap,
		E extends ValidContentEntrySlug<C> | (string & {}),
	>(
		collection: C,
		slug: E,
	): E extends ValidContentEntrySlug<C>
		? Promise<CollectionEntry<C>>
		: Promise<CollectionEntry<C> | undefined>;
	export function getEntry<
		C extends keyof DataEntryMap,
		E extends keyof DataEntryMap[C] | (string & {}),
	>(
		collection: C,
		id: E,
	): E extends keyof DataEntryMap[C]
		? Promise<DataEntryMap[C][E]>
		: Promise<CollectionEntry<C> | undefined>;

	/** Resolve an array of entry references from the same collection */
	export function getEntries<C extends keyof ContentEntryMap>(
		entries: {
			collection: C;
			slug: ValidContentEntrySlug<C>;
		}[],
	): Promise<CollectionEntry<C>[]>;
	export function getEntries<C extends keyof DataEntryMap>(
		entries: {
			collection: C;
			id: keyof DataEntryMap[C];
		}[],
	): Promise<CollectionEntry<C>[]>;

	export function render<C extends keyof AnyEntryMap>(
		entry: AnyEntryMap[C][string],
	): Promise<RenderResult>;

	export function reference<C extends keyof AnyEntryMap>(
		collection: C,
	): import('astro/zod').ZodEffects<
		import('astro/zod').ZodString,
		C extends keyof ContentEntryMap
			? {
					collection: C;
					slug: ValidContentEntrySlug<C>;
				}
			: {
					collection: C;
					id: keyof DataEntryMap[C];
				}
	>;
	// Allow generic `string` to avoid excessive type errors in the config
	// if `dev` is not running to update as you edit.
	// Invalid collection names will be caught at build time.
	export function reference<C extends string>(
		collection: C,
	): import('astro/zod').ZodEffects<import('astro/zod').ZodString, never>;

	type ReturnTypeOrOriginal<T> = T extends (...args: any[]) => infer R ? R : T;
	type InferEntrySchema<C extends keyof AnyEntryMap> = import('astro/zod').infer<
		ReturnTypeOrOriginal<Required<ContentConfig['collections'][C]>['schema']>
	>;

	type ContentEntryMap = {
		"blog": {
"2026-04-25.mdx": {
	id: "2026-04-25.mdx";
  slug: "2026-04-25";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-04-26.mdx": {
	id: "2026-04-26.mdx";
  slug: "2026-04-26";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-04-27.mdx": {
	id: "2026-04-27.mdx";
  slug: "2026-04-27";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-04-28.mdx": {
	id: "2026-04-28.mdx";
  slug: "2026-04-28";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-04-29.mdx": {
	id: "2026-04-29.mdx";
  slug: "2026-04-29";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-04-30.mdx": {
	id: "2026-04-30.mdx";
  slug: "2026-04-30";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-01.mdx": {
	id: "2026-05-01.mdx";
  slug: "2026-05-01";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-04.mdx": {
	id: "2026-05-04.mdx";
  slug: "2026-05-04";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-05.mdx": {
	id: "2026-05-05.mdx";
  slug: "2026-05-05";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-06-ai-dx-news.mdx": {
	id: "2026-05-06-ai-dx-news.mdx";
  slug: "2026-05-06-ai-dx-news";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-06-beginner-guide.mdx": {
	id: "2026-05-06-beginner-guide.mdx";
  slug: "2026-05-06-beginner-guide";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-06.mdx": {
	id: "2026-05-06.mdx";
  slug: "2026-05-06";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-07-ai-dx-news.mdx": {
	id: "2026-05-07-ai-dx-news.mdx";
  slug: "2026-05-07-ai-dx-news";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-07-beginner-guide.mdx": {
	id: "2026-05-07-beginner-guide.mdx";
  slug: "2026-05-07-beginner-guide";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-07.mdx": {
	id: "2026-05-07.mdx";
  slug: "2026-05-07";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-08-ai-dx-news.mdx": {
	id: "2026-05-08-ai-dx-news.mdx";
  slug: "2026-05-08-ai-dx-news";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-08-beginner-guide.mdx": {
	id: "2026-05-08-beginner-guide.mdx";
  slug: "2026-05-08-beginner-guide";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-08.mdx": {
	id: "2026-05-08.mdx";
  slug: "2026-05-08";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-09-ai-dx-news.mdx": {
	id: "2026-05-09-ai-dx-news.mdx";
  slug: "2026-05-09-ai-dx-news";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-09-beginner-guide.mdx": {
	id: "2026-05-09-beginner-guide.mdx";
  slug: "2026-05-09-beginner-guide";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-17-heygen-jikoshokai.mdx": {
	id: "2026-05-17-heygen-jikoshokai.mdx";
  slug: "2026-05-17-heygen-jikoshokai";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-17-ion-owners-card.mdx": {
	id: "2026-05-17-ion-owners-card.mdx";
  slug: "2026-05-17-ion-owners-card";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-18-author-life-childhood-elementary.mdx": {
	id: "2026-05-18-author-life-childhood-elementary.mdx";
  slug: "2026-05-18-author-life-childhood-elementary";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-18-author-life-elementary-middle-school.mdx": {
	id: "2026-05-18-author-life-elementary-middle-school.mdx";
  slug: "2026-05-18-author-life-elementary-middle-school";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-18-kinketsu.mdx": {
	id: "2026-05-18-kinketsu.mdx";
  slug: "2026-05-18-kinketsu";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"2026-05-19-volunteer-visit-nagaoka-komehyappyo-support-center.mdx": {
	id: "2026-05-19-volunteer-visit-nagaoka-komehyappyo-support-center.mdx";
  slug: "2026-05-19-volunteer-visit-nagaoka-komehyappyo-support-center";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"ai-dx-learning-roadmap.mdx": {
	id: "ai-dx-learning-roadmap.mdx";
  slug: "ai-dx-learning-roadmap";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"ai-hallucination-checklist.mdx": {
	id: "ai-hallucination-checklist.mdx";
  slug: "ai-hallucination-checklist";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"attachment-style-workplace.mdx": {
	id: "attachment-style-workplace.mdx";
  slug: "attachment-style-workplace";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"book-review-business-process-dx-guide.mdx": {
	id: "book-review-business-process-dx-guide.mdx";
  slug: "book-review-business-process-dx-guide";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"claude-code-dx-case-study-1.mdx": {
	id: "claude-code-dx-case-study-1.mdx";
  slug: "claude-code-dx-case-study-1";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"claude-vs-chatgpt-gyomu-hikaku.mdx": {
	id: "claude-vs-chatgpt-gyomu-hikaku.mdx";
  slug: "claude-vs-chatgpt-gyomu-hikaku";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"etf-1489-2516-hikaku-nisa.mdx": {
	id: "etf-1489-2516-hikaku-nisa.mdx";
  slug: "etf-1489-2516-hikaku-nisa";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"g-kentei-2026-jukken-report.mdx": {
	id: "g-kentei-2026-jukken-report.mdx";
  slug: "g-kentei-2026-jukken-report";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"gemini-lyria3-pro-music-creation.mdx": {
	id: "gemini-lyria3-pro-music-creation.mdx";
  slug: "gemini-lyria3-pro-music-creation";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"haito-kabu-erabikata-shoshinja.mdx": {
	id: "haito-kabu-erabikata-shoshinja.mdx";
  slug: "haito-kabu-erabikata-shoshinja";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"haito-kin-kakutei-bi-schedule.mdx": {
	id: "haito-kin-kakutei-bi-schedule.mdx";
  slug: "haito-kin-kakutei-bi-schedule";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"haito-saito-rishi-keisan-hoho.mdx": {
	id: "haito-saito-rishi-keisan-hoho.mdx";
  slug: "haito-saito-rishi-keisan-hoho";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"hallucination-ai-lesson.mdx": {
	id: "hallucination-ai-lesson.mdx";
  slug: "hallucination-ai-lesson";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"industrial-counselor.mdx": {
	id: "industrial-counselor.mdx";
  slug: "industrial-counselor";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"ion-kabu-keii-column.mdx": {
	id: "ion-kabu-keii-column.mdx";
  slug: "ion-kabu-keii-column";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"kabu-yutai-nisa-osusume.mdx": {
	id: "kabu-yutai-nisa-osusume.mdx";
  slug: "kabu-yutai-nisa-osusume";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"kddi-haito-yutai-hikaku.mdx": {
	id: "kddi-haito-yutai-hikaku.mdx";
  slug: "kddi-haito-yutai-hikaku";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"kirin-ajinomoto-haito-shokuhin.mdx": {
	id: "kirin-ajinomoto-haito-shokuhin.mdx";
  slug: "kirin-ajinomoto-haito-shokuhin";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"kohaito-etf-1489-tokuchou.mdx": {
	id: "kohaito-etf-1489-tokuchou.mdx";
  slug: "kohaito-etf-1489-tokuchou";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"mental-health-management-2shu-goukaku.mdx": {
	id: "mental-health-management-2shu-goukaku.mdx";
  slug: "mental-health-management-2shu-goukaku";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"mitsubishi-hc-capital-renzon-zozai.mdx": {
	id: "mitsubishi-hc-capital-renzon-zozai.mdx";
  slug: "mitsubishi-hc-capital-renzon-zozai";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"nihon-kabu-kohaito-ranking.mdx": {
	id: "nihon-kabu-kohaito-ranking.mdx";
  slug: "nihon-kabu-kohaito-ranking";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"nihon-yusen-kaisen-haito.mdx": {
	id: "nihon-yusen-kaisen-haito.mdx";
  slug: "nihon-yusen-kaisen-haito";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"nisa-haito-kabu-poruto.mdx": {
	id: "nisa-haito-kabu-poruto.mdx";
  slug: "nisa-haito-kabu-poruto";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"nisa-tsumitate-index-vs-haito.mdx": {
	id: "nisa-tsumitate-index-vs-haito.mdx";
  slug: "nisa-tsumitate-index-vs-haito";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"sc-joho-anzen-shien-shi-benkyoho.mdx": {
	id: "sc-joho-anzen-shien-shi-benkyoho.mdx";
  slug: "sc-joho-anzen-shien-shi-benkyoho";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"sekisui-house-haito-ruishin.mdx": {
	id: "sekisui-house-haito-ruishin.mdx";
  slug: "sekisui-house-haito-ruishin";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"shoken-kouza-haito-kabu-erabikata.mdx": {
	id: "shoken-kouza-haito-kabu-erabikata.mdx";
  slug: "shoken-kouza-haito-kabu-erabikata";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"stress-coping-methods.mdx": {
	id: "stress-coping-methods.mdx";
  slug: "stress-coping-methods";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"takeda-yakuhin-haito-2026.mdx": {
	id: "takeda-yakuhin-haito-2026.mdx";
  slug: "takeda-yakuhin-haito-2026";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
"toyoda-jidosha-haito-ev.mdx": {
	id: "toyoda-jidosha-haito-ev.mdx";
  slug: "toyoda-jidosha-haito-ev";
  body: string;
  collection: "blog";
  data: InferEntrySchema<"blog">
} & { render(): Render[".mdx"] };
};

	};

	type DataEntryMap = {
		
	};

	type AnyEntryMap = ContentEntryMap & DataEntryMap;

	export type ContentConfig = typeof import("./../../src/content/config.js");
}
