// Naver Search Advisor's site-ownership file (searchadvisor.naver.com). It has to answer at this
// exact .html URL, but Pages redirects every /<name>.html asset to /<name>, so a file in public/
// would only ever give Naver a 308. A function at this path answers before that redirect.
export const onRequest = () =>
  new Response("naver-site-verification: naveradb78f7752021d2dd54f6bdbcd921b93.html", {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
