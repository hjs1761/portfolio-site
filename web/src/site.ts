export const site = {
  name: '황준석',
  nameEn: 'Junseok Hwang',
  role: 'Backend Engineer',
  // 공개 전 확인 필요 (설계 문서 §12-1)
  email: 'hjs1761@gmail.com',
  description:
    '커머스 운영 7년차 백엔드 개발자 황준석의 포트폴리오. 커머스 쇼핑몰 운영과 사내 업무 도구 프로젝트.',
  nav: [
    { href: '/projects/', label: '프로젝트' },
    { href: '/ai/', label: 'AI와 일하는 방식' },
    { href: '/resume/', label: '이력서' },
    { href: 'https://hjs1761.tistory.com/', label: '블로그' },
  ],
  updated: '2026-10-18',
  // Cloudflare Web Analytics 사이트 토큰(페이지에 그대로 드러나는 공개 값). 비우면 통계 스크립트를 넣지 않는다.
  analyticsToken: '1dbce57665034bcdb92a770f79f12786',
} as const;
