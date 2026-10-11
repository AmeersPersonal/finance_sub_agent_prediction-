// Keyboard handler for tablists with roving tabindex (arrows, Home, End).
export function useRoving(values, value, onChange) {
  return (event, index) => {
    let next;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % values.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + values.length - 1) % values.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = values.length - 1;
    else return;
    event.preventDefault();
    onChange(values[next]);
    event.currentTarget.parentElement.querySelectorAll('[role=tab]')[next]?.focus();
  };
}
