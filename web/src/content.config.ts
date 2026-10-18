import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const projects = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/projects' }),
  schema: z.object({
    // 제목은 프로젝트 이름 그대로 쓴다(카피 문구 금지)
    title: z.string(),
    summary: z.string(),
    group: z.enum(['client', 'internal']),
    order: z.number(),
    // 첫 화면에 올리는 대표 프로젝트
    featured: z.boolean().default(false),
    period: z.string(),
    client: z.string(),
    role: z.string(),
    stack: z.array(z.string()),
    links: z
      .array(
        z.object({
          label: z.string(),
          url: z.url(),
        }),
      )
      .default([]),
    // 공개 페이지 캡처만. 관리자·사내 화면은 시험 데이터로 찍은 것만 올린다
    shots: z
      .array(
        z.object({
          src: z.string(),
          alt: z.string(),
          host: z.string(),
          caption: z.string(),
        }),
      )
      .default([]),
    // 근거 출처 메모. 화면에는 표시하지 않는다(공개 원칙 검토용).
    source: z.string(),
  }),
});

const resume = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/resume' }),
  schema: z.object({
    title: z.string(),
  }),
});

export const collections = { projects, resume };
