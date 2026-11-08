export default [{
  prefix: '/data-screen/',
  load: () => import('./views/data-screen/bootstrap'),
}, {
  prefix: '/web-terminal/',
  load: () => import('./views/web-terminal/bootstrap'),
}];
