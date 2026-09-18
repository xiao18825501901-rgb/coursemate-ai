import React from 'react';
const paths = {
    user: 'M20 21v-2a7 7 0 0 0-14 0v2M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
    dashboard: 'M3 13a9 9 0 1 1 18 0v6H3zM12 13l4-5M6 10h.01M7 6h.01M12 4h.01M18 10h.01',
    courses: 'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5',
    calendar: 'M4 5h16v16H4zM4 9h16M8 3v4M16 3v4M8 13h2M14 13h2M8 17h2M14 17h2',
    inbox: 'M3 8h18v13H3zM7 8V3h10v5M3 13h5l2 3h4l2-3h5',
    help: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M9 9a3 3 0 1 1 4 3c-1 .5-1 1-1 3M12 18h.01',
    book: 'M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1v15',
    plus: 'M12 5v14M5 12h14', close: 'M6 6l12 12M18 6L6 18', check: 'M5 12l4 4L19 6',
    comment: 'M3 4h18v13H9l-6 4V4', folder: 'M3 5h6l2 3h10v12H3z', file: 'M5 2h9l5 5v15H5zM14 2v6h5M8 13h8M8 17h5',
    more: 'M12 5h.01M12 12h.01M12 19h.01', search: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14M15 15l6 6',
    download: 'M12 3v12M7 10l5 5 5-5M4 16v5h16v-5', back: 'M19 12H5l6-6M5 12l6 6', arrow: 'M9 5l7 7-7 7',
    down: 'M5 9l7 7 7-7', up: 'M5 15l7-7 7 7', expand: 'M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6',
    collapse: 'M9 3v6H3M15 3v6h6M21 15h-6v6M3 15h6v6', history: 'M3 11a9 9 0 1 1 2 7M3 5v6h6M12 7v5l3 2',
    send: 'M22 2L9 15M22 2l-7 20-6-7-7-6z', tree: 'M10 2h4v4h-4zM2 18h5v4H2zM10 18h4v4h-4zM17 18h5v4h-5zM12 6v12M4.5 18v-6h15v6',
    settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2',
    bell: 'M4 17h16l-2-4V9a6 6 0 0 0-12 0v4zM9 20a3 3 0 0 0 6 0', lock: 'M5 10h14v12H5zM8 10V6a4 4 0 0 1 8 0v4',
    edit: 'M4 16L16 4l4 4L8 20H4zM14 6l4 4', trash: 'M3 6h18M8 6V3h8v3M6 6l1 15h10l1-15M10 10v7M14 10v7',
    heart: 'M12 21l-9-9a6 6 0 0 1 9-8 6 6 0 0 1 9 8z', mail: 'M3 4h18v16H3zM3 5l9 7 9-7', logout: 'M9 3H3v18h6M9 12h12M16 7l5 5-5 5',
    attach: 'M7 13l7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9', stop: 'M5 5h14v14H5z', info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 10v7M12 6h.01',
    shareCourse: 'M5 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4M19 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4M19 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4M6 8h3l4 5M9 13l4 5h3M7 6v3M17 6v3M17 18v-3M7 18v-3'
};
export function Icon({ name, ...props }) { return <svg className="ico" viewBox="0 0 24 24" aria-hidden="true" {...props}><path d={paths[name] || paths.book}/></svg>; }
export function IconButton({ name, title, onClick, ...props }) { return <button type="button" className="icon-btn" title={title} aria-label={title} onClick={onClick} {...props}><Icon name={name}/></button>; }
export function Avatar({ name = '' }) { return <div className="avatar">{name.slice(0, 2) || 'CM'}</div>; }
